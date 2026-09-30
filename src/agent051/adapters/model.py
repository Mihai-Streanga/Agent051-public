"""
Singurul loc din tot proiectul care atinge cu adevarat un model.

Pana in faza 2, Agent 051 detinea TOATA logica legata de model - schema, promptul,
validarea - dar NU facea niciodata apelul. Functia care vorbeste cu modelul se primea
din afara, ca parametru (`cheama_model`), iar cine o dadea, ala platea si ala tinea cheia.

FAZA 2 SCHIMBA DOAR CINE UMPLE SEAMUL, nu seamul in sine.
Planul initial era ca JA.S.Mine sa injecteze functia prin MCP. Nu merge: MCP lasa clientul
sa CHEME unelte, nu sa INJECTEZE functii, iar "sampling" din specificatia MCP nu e
suportat in Open WebUI - si oricum ar inversa dependenta (agentul ar putea normaliza
doar cand JA.S.Mine e pornita). Decizia: agentul e autonom. Cheie proprie in .env, injectie
proprie. JA.S.Mine ramane consumator de fapte, nu furnizor de model.

Deci acum agentul isi construieste SINGUR `cheama_model` - aici, in acest fisier. Restul
regulii ramane neatins:
  - core/ tot nu vede niciodata o cheie si tot primeste modelul ca parametru injectat;
    in teste injectam functii inventate, exact ca pana acum.
  - un singur fisier atinge reteaua si biblioteca `anthropic`, si acela e asta.

DE CE importul lui `anthropic` e AMANAT (inauntrul functiei, nu in capul modulului):
ca modulul asta sa poata fi importat chiar si fara biblioteca instalata. Uneltele
deterministe (ingestie, extragere, filtrare) si TOATE testele trec prin lanturi care
importa adaptoare - iar daca `import anthropic` ar sta sus, ele ar cadea la pornire pe o
masina fara biblioteca instalata, desi n-au nevoie de niciun model. Asa, biblioteca e
ceruta abia in clipa in care chiar dai un apel.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Radacina proiectului: urcam trei niveluri (adapters -> agent051 -> src -> radacina).
RADACINA_PROIECT = Path(__file__).resolve().parents[3]

# Nu exista model implicit. Pana la 30 sept. 2026, lipsa lui MODEL_NORMALIZARE din .env
# muta tacut agentul pe un Haiku - adica alt judecator decat cel ales (Sonnet 5),
# fara ca cineva sa fi hotarat asta. Acum lipsa opreste rularea, ca lipsa cheii.

# Cat de lung poate fi raspunsul. Raspunsurile noastre sunt un JSON de cateva campuri,
# dar Sonnet 5 GANDESTE inainte sa raspunda, iar gandirea se scade din aceeasi limita.
# La 1024, pe 29 septembrie 2026, a treia evaluare a rularii din JA.S.Mine a iesit
# taiata si a oprit rularea (33 de apeluri numarate, 32 scrise in baza). Se plateste
# doar ce scrie modelul, nu limita - deci 4096 nu scumpeste un anunt, doar lasa loc.
# Daca tot se intampla, raspunsul taiat iese ca RaspunsTaiat si opreste rularea - nu ca
# o respingere.
MAX_TOKENI = 4096


class EroareInfrastructura(Exception):
    """
    Ceva din DRUMUL catre model s-a rupt - nu continutul unui raspuns.

    DE CE un tip separat, si de ce conteaza enorm:
    "modelul a respins anuntul" si "n-am putut ajunge la model" sunt lucruri complet
    diferite, dar pana acum aratau identic - amandoua ieseau ca "respins". Asa, o
    biblioteca lipsa marca 50 de anunturi drept "modelul le-a gasit proaste", cand de
    fapt modelul nici n-a fost chemat. E o minciuna care se strecoara tacut in baza.

    Un esec de INFRASTRUCTURA (biblioteca neinstalata, cheie lipsa sau respinsa, retea
    picata, API cazut) inseamna ca nu STIM nimic despre anunt - deci nu-l atingem, nu-l
    marcam si OPRIM rularea la prima aparitie: daca lipseste biblioteca la primul anunt,
    va lipsi si la al 50-lea. O RESPINGERE DE CONTINUT (modelul a raspuns, dar raspunsul
    n-a trecut validarea) e altceva - aia chiar e o parere despre anunt, se salveaza si
    rularea merge mai departe.

    Regula practica: exceptia asta se ridica DOAR aici, in stratul care atinge modelul.
    Ce iese din functia care valideaza (core/) nu e niciodata infrastructura - e continut.
    """


class RaspunsTaiat(EroareInfrastructura):
    """
    Modelul a raspuns, dar a fost oprit de limita de lungime (MAX_TOKENI) - raspunsul e taiat.

    DE CE nu e o respingere de continut: un JSON taiat la jumatate pica validarea si ar
    iesi "respins", adica o parere despre anunt pe care modelul n-a dat-o. Nu stim nimic
    despre anunt - exact ca la un esec de drum. De aia e un caz de EroareInfrastructura:
    adaptoarele care o prind deja opresc rularea si nu ating anuntul, fara nicio schimbare.

    DE CE un tip separat totusi: mesajul trebuie sa spuna ce s-a intamplat, iar apelul
    SE FACTUREAZA (spre deosebire de o retea cazuta). Tokenii vin cu exceptia, ca
    contorul sa-i poata numara inainte s-o lase sa treaca.
    """

    def __init__(self, tokeni_intrare: int, tokeni_iesire: int):
        super().__init__(
            f"Raspunsul modelului a fost taiat la limita de {MAX_TOKENI} tokeni. "
            "Anuntul nu s-a atins; limita sau promptul trebuie revazute."
        )
        self.tokeni_intrare = tokeni_intrare
        self.tokeni_iesire = tokeni_iesire


class ContorCost:
    """
    Tine socoteala a ce a costat o rulare: cate apeluri, cati tokeni intrare/iesire.

    DE CE exista, cand `cheama_model` e doar (str) -> str si n-are cum sa raporteze cifre:
    apelurile costa bani reali, iar banii care nu se vad se cheltuie fara masura. Contorul
    e obiectul mic in care functia de model isi noteaza, dupa fiecare apel reusit, ce a
    consumat. Rularea il citeste la sfarsit si il aduna in `stare`.

    Numaram DOAR apelurile reusite (cele care au primit un raspuns de la model). Un apel
    care pica pe retea nu a consumat tokeni si nu se factureaza, deci nu se numara. Un
    apel care intoarce un JSON stricat SE numara: modelul a raspuns, deci e facturat -
    faptul ca raspunsul e prost nu-l face gratis.
    """

    def __init__(self):
        self.apeluri = 0
        self.tokeni_intrare = 0
        self.tokeni_iesire = 0

    @property
    def tokeni_total(self) -> int:
        return self.tokeni_intrare + self.tokeni_iesire


def cheama_model_real(prompt: str) -> str:
    """
    Implementarea reala a lui `cheama_model`: primeste un text, intoarce un text.

    Aceasta e forma ceruta de restul lantului - aceeasi semnatura (str) -> str ca a
    functiilor inventate din teste. Nu numara nimic; daca vrei si socoteala costului,
    foloseste `construieste_cheama_model(contor)`, care face acelasi apel dar isi noteaza
    consumul in contor.

    NU face retry. Un anunt = un apel. Daca reteaua pica sau cheia e gresita, ridica o
    exceptie clara, iar cel care a chemat (normalizeaza_anunt / evalueaza_anunt) o prinde
    si o transforma in "respins, cu motiv" - fara sa opreasca rularea si fara sa incerce
    din nou in tacere. Reincercarea, daca o vrem, se cere explicit.
    """
    text, _intrare, _iesire = _apeleaza_modelul(prompt)
    return text


def construieste_cheama_model(contor: ContorCost):
    """
    Construieste un `cheama_model` care, pe langa apel, isi noteaza consumul in `contor`.

    Intoarce o functie (str) -> str, exact ca `cheama_model_real` - restul lantului nu
    vede nicio diferenta. Diferenta e ca, dupa fiecare apel reusit, aici se aduna un apel
    si tokenii lui in contorul dat. Asa, rularea poate raporta la sfarsit ce a costat,
    fara ca vreo bucata din core/ sa stie ceva despre bani sau tokeni.

    Incrementarea se face DUPA ce apelul a reusit. Daca `_apeleaza_modelul` ridica o
    exceptie (retea cazuta), liniile de numarare nu se mai executa - exact ce vrem: un
    apel care n-a ajuns la model nu a costat nimic, deci nu se numara.
    """

    def cheama(prompt: str) -> str:
        try:
            text, intrare, iesire = _apeleaza_modelul(prompt)
        except RaspunsTaiat as taiat:
            # Singurul esec care se factureaza: modelul a scris pana la limita.
            contor.apeluri += 1
            contor.tokeni_intrare += taiat.tokeni_intrare
            contor.tokeni_iesire += taiat.tokeni_iesire
            raise
        contor.apeluri += 1
        contor.tokeni_intrare += intrare
        contor.tokeni_iesire += iesire
        return text

    return cheama


def _cheie_api() -> str:
    """
    Cheia proprie a agentului, din .env (ANTHROPIC_API_KEY).

    Reincarcam .env la fiecare apel, ca la mcp_server: asa vede ce e in fisier ACUM, nu
    ce era cand s-a importat modulul. Lipsa cheii nu se ghiceste si nu se ascunde - iese
    ca EroareInfrastructura, care opreste rularea (vezi verifica_infrastructura).
    """
    load_dotenv(RADACINA_PROIECT / ".env")
    cheie = os.getenv("ANTHROPIC_API_KEY")
    return cheie.strip() if cheie else ""


def cheie_prezenta() -> bool:
    """
    Spune DOAR daca exista o cheie in .env, niciodata care e.

    Exista ca porneste_mcp.py sa poata anunta la pornire ca serverul expune unelte care
    cheama modelul fara sa aiba cu ce - altfel lipsa se afla abia la primul apel, dupa
    ce cineva a chemat normalizeaza() din JA.S.Mine si a primit o eroare fara context.
    Intoarce un adevarat/fals tocmai ca valoarea sa nu poata ajunge din greseala pe ecran.

    Nu garanteaza ca cheia e si VALIDA - aia se afla doar la primul apel (un 401).
    """
    return bool(_cheie_api())


def model_configurat():
    """
    Ce model folosim, din .env (MODEL_NORMALIZARE). None daca lipseste.

    Numele variabilei e istoric: aceeasi valoare alege modelul si pentru evaluarea
    calitativa, nu doar pentru normalizare.

    Publica fiindca o cere si raportul de cost: preturile din config/cost.yaml se
    folosesc doar daca sunt ale acestui model. None nu se "repara" aici: rularea reala
    se opreste in verifica_infrastructura, iar raportul de cost spune ca lipseste.
    """
    load_dotenv(RADACINA_PROIECT / ".env")
    valoare = os.getenv("MODEL_NORMALIZARE")
    return valoare.strip() if valoare and valoare.strip() else None


def _model_sau_eroare() -> str:
    """Modelul din .env, sau EroareInfrastructura daca lipseste - nu un model ghicit."""
    model = model_configurat()
    if not model:
        raise EroareInfrastructura(
            "MODEL_NORMALIZARE lipseste din .env - agentul nu stie ce model sa cheme. "
            "Pune acolo modelul din config/cost.yaml."
        )
    return model


def verifica_infrastructura() -> None:
    """
    Verifica INAINTE de lot ca se poate ajunge la model. La lipsa, ridica EroareInfrastructura.

    Se cheama o singura data, la inceputul unei rulari reale, ca sa afli din prima ca
    lipseste biblioteca sau cheia - nu dupa ce ai marcat gresit 50 de anunturi. Verifica
    doar ce se poate sti FARA sa cheltui un apel: biblioteca importabila si cheia prezenta.
    Daca cheia exista dar e gresita, asta se afla abia la primul apel (un 401), care o
    opreste si el rularea imediat - dar atunci un singur anunt a fost atins, nu 50.

    Mesajele spun omului exact ce sa faca. Un dry run NU are nevoie de asta (nu cheama
    modelul), de aia verificarea se face doar pe drumul real, in ruleaza_*.
    """
    if not _cheie_api():
        raise EroareInfrastructura(
            "ANTHROPIC_API_KEY lipseste din .env - agentul nu are cu ce chema modelul."
        )
    _model_sau_eroare()
    try:
        import anthropic  # noqa: F401
    except ImportError as eroare:
        raise EroareInfrastructura(
            "Biblioteca `anthropic` nu e instalata. "
            "Ruleaza: pip install -r requirements.txt"
        ) from eroare


def _apeleaza_modelul(prompt: str):
    """
    Apelul propriu-zis. Intoarce (text, tokeni_intrare, tokeni_iesire).

    Aici, si numai aici, se importa `anthropic`, se construieste clientul si se atinge
    reteaua. Importul e amanat dinadins (vezi nota de sus): fara el, importul acestui
    modul ar cere biblioteca instalata chiar si pentru fluxurile care n-o folosesc.

    Orice problema de DRUM - lipsa cheii, biblioteca neinstalata, cheie respinsa (401),
    retea cazuta, API cazut - iese ca EroareInfrastructura, cu mesaj clar. NU o reparam,
    nu reincercam, si mai ales NU o lasam sa treaca drept un raspuns prost al modelului:
    cel care a chemat trebuie sa poata deosebi "modelul a zis nu" de "n-am ajuns la model".
    """
    cheie = _cheie_api()
    if not cheie:
        raise EroareInfrastructura(
            "ANTHROPIC_API_KEY lipseste din .env - agentul nu are cu ce chema modelul."
        )

    # Import amanat: vezi nota din capul fisierului.
    try:
        import anthropic
    except ImportError as eroare:
        raise EroareInfrastructura(
            "Biblioteca `anthropic` nu e instalata. "
            "Ruleaza: pip install -r requirements.txt"
        ) from eroare

    model = _model_sau_eroare()
    client = anthropic.Anthropic(api_key=cheie)
    try:
        raspuns = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENI,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError as eroare:
        raise EroareInfrastructura(
            "Cheia API a fost respinsa de Anthropic (401). "
            "Verifica ANTHROPIC_API_KEY din .env."
        ) from eroare
    except anthropic.APIConnectionError as eroare:
        raise EroareInfrastructura(
            f"Nu s-a putut ajunge la API-ul Anthropic (retea?): {eroare}"
        ) from eroare
    except anthropic.APIStatusError as eroare:
        # Orice alt raspuns non-2xx: limita de cereri (429), server cazut (5xx) etc.
        raise EroareInfrastructura(
            f"API-ul Anthropic a raspuns cu eroare ({eroare.status_code})."
        ) from eroare
    except anthropic.APIError as eroare:
        # Plasa pentru orice alta eroare venita din biblioteca, ca sa nu scape una
        # neimbracata si sa fie confundata cu o respingere de continut.
        raise EroareInfrastructura(
            f"Eroare la apelul catre Anthropic: {eroare}"
        ) from eroare

    return _rezultat_din_raspuns(raspuns)


def _rezultat_din_raspuns(raspuns):
    """
    Din raspunsul primit: (text, tokeni_intrare, tokeni_iesire), sau RaspunsTaiat.

    Separat de apel ca sa se poata testa fara retea, pe un raspuns inventat.
    """
    intrare = raspuns.usage.input_tokens
    iesire = raspuns.usage.output_tokens
    if getattr(raspuns, "stop_reason", None) == "max_tokens":
        raise RaspunsTaiat(intrare, iesire)
    return _text_din_raspuns(raspuns), intrare, iesire


def _text_din_raspuns(raspuns) -> str:
    """
    Scoate textul din raspunsul modelului.

    Raspunsul vine ca o lista de blocuri; noua ne trebuie primul bloc de tip text. Le
    parcurgem si il luam pe primul - nu presupunem ca e mereu pe pozitia zero, ca sa nu
    ne surprinda un bloc de alt fel strecurat inainte. Daca nu exista niciun bloc de text,
    intoarcem sir gol: validarea din core/ il va respinge ca "raspuns gol", ceea ce e
    exact tratamentul corect - nu inventam un continut care nu a venit.
    """
    for bloc in raspuns.content:
        if getattr(bloc, "type", None) == "text":
            return bloc.text
    return ""
