"""
Din HTML-ul unei pagini de anunt: descrierea, si (din 2026) numele firmei si titlul real.
Cate o functie per sursa.

FUNCTIE PURA, ca tot ce sta in core/: primeste un sir, intoarce un dictionar. Nu cere
pagina, nu o salveaza, nu atinge reteaua sau discul. De aceea se testeaza pe pagini
salvate pe disc, cu internetul taiat - vezi tests/test_descriere.py si fixture-urile
din tests/pagini/, care sunt bucati de pagini REALE, nu HTML inventat de noi.

DE CE conteaza ca etapa asta e separata de cerere:
HTML-ul brut se salveaza in baza (coloana `pagina_html`). Daca peste o luna se dovedeste
ca parserul a ratat salariul, sau ca eJobs si-a schimbat sablonul, se rescriu functiile
de aici si se re-extrage din ce e deja salvat - fara sa se atinga reteaua, fara sa se
mai ceara o data 500 de pagini si fara sa depinda de faptul ca anunturile mai exista.
Aceeasi regula ca la mailuri, si a fost platita o data.

CUM CITESTE FIECARE SURSA - stabilit uitandu-ne la pagini reale, nu ghicit:
  eJobs    are un bloc <script type="application/ld+json"> cu schema.org, iar in el un
           nod @type: "JobPosting" cu campul `description`. E un standard public, pe
           care site-ul il tine pentru Google - deci se schimba mult mai rar decat
           clasele CSS, care se schimba la fiecare reproiectare.
  BestJobs e o aplicatie Next.js: tot ce afiseaza pagina sta intr-un
           <script id="__NEXT_DATA__"> cu JSON, la props.pageProps.job.description.
           Tot date structurate, tot mai stabil decat markup-ul.
Amandoua intorc descrierea ca HTML (<p>, <li>, <br/>), nu ca text - de aia mai trece
o data prin _html_in_text().

ESECUL SE MOTIVEAZA, NU SE ASCUNDE. Cand structura nu se recunoaste, intoarcem
{"ok": False, "motiv": "..."} cu motivul exact - niciodata un sir gol. Un sir gol
salvat in baza arata identic cu "anuntul chiar n-are descriere", si atunci n-ai cum sa
stii daca trebuie reparat parserul sau nu. Aceeasi regula ca la validarea raspunsurilor
de model: respingem, nu reparam.

Fisierul nu importa nimic din afara Python-ului: json, re, html.parser si urllib.parse.
"""

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

# Sursele pe care le stim citi. O sursa necunoscuta iese ca esec motivat, nu ca
# descriere goala - vezi extrage_descrierea().
SURSE_CUNOSCUTE = ("ejobs", "bestjobs")

# Etichetele dupa care textul continua pe rand nou. Fara ele, toata descrierea ar iesi
# ca un singur bloc lipit: "...experienta anterioaraResponsabilitati...".
ETICHETE_DE_RUPERE = (
    "p", "br", "div", "li", "ul", "ol", "tr", "table",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
)


def pagina_e_a_anuntului(adresa_ceruta: str, adresa_finala: str) -> bool:
    """
    Pagina la care am ajuns e chiar anuntul cerut, sau serverul ne-a trimis in alta parte?

    DE CE EXISTA, si e o lectie platita pe 17 august 2026: eJobs nu raspunde cu 404 la un
    anunt care nu mai e. Raspunde cu 302 catre lista generala de joburi - deci cod 200 si
    o pagina intreaga, valida, doar ca a altcuiva. Parserul nu gasea niciun JobPosting in
    ea (corect, nu era niciunul) si toate trei anunturile ieseau `fara_descriere`, adica
    "repara parserul". Parserul n-avea nimic. Pagina nu era a lor.
    Confuzia costa dublu: arata o datorie care nu exista si ascunde faptul adevarat.

    REGULA, si e singura: ultima bucata din adresa CERUTA - la eJobs si BestJobs, aia e
    identificatorul anuntului - trebuie sa se regaseasca intre bucatile adresei FINALE.

        cerut : /user/locuri-de-munca/j/1976203
        final : /locuri-de-munca                          -> nu, ne-a trimis la lista
        cerut : /user/locuri-de-munca/j/1974474
        final : /user/locuri-de-munca/customer-support/1974474  -> da, acelasi anunt

    Al doilea caz e chiar motivul pentru care nu comparam adresele cap-coada: eJobs
    redirecteaza legitim forma scurta `/j/<id>` catre cea cu nume in adresa, si aia e tot
    pagina anuntului. Ce se pastreaza intre ele e identificatorul; el e intrebarea.

    Ce NU face: nu ghiceste sursa, nu se uita in HTML, nu decide ce status se scrie in
    baza. Raspunde la o singura intrebare, cu doua siruri.

    ADRESA FINALA GOALA INSEAMNA "DA". Nu stim de nicio redirectare, deci nu inventam una:
    un "nu" scos dintr-o lipsa de informatie ar marca anunturi vii ca expirate, si asta e
    exact greseala pe care EroareRetea o previne in ingest/pagini.py.
    """
    ceruta = (adresa_ceruta or "").strip()
    finala = (adresa_finala or "").strip()

    if not ceruta or not finala:
        return True

    bucati_cerute = _bucatile_adresei(ceruta)
    if not bucati_cerute:
        return True

    return bucati_cerute[-1] in _bucatile_adresei(finala)


def _bucatile_adresei(adresa: str) -> list:
    """
    Bucatile negoale din calea unei adrese, cu litera mica.

    Prin urlparse, nu prin despicat de mana: asa cad de la sine si parametrii (`?utm=...`)
    si ancorele (`#aplica`), care n-au nimic de-a face cu ce pagina e.
    """
    cale = urlparse(adresa).path
    return [bucata.lower() for bucata in cale.split("/") if bucata]


def extrage_descrierea(html: str, sursa: str) -> dict:
    """
    Descrierea unui anunt, din HTML-ul paginii lui.

    Intoarce:
        {"ok": True,  "descriere": "..."}    text curat, negol
        {"ok": False, "motiv": "..."}        nu s-a putut, cu motivul exact

    `sursa` alege parserul ("ejobs" / "bestjobs"). Nu ghicim sursa din HTML: o stim deja,
    e in baza, pusa la extragerea din mail. A o re-deduce ar insemna inca un loc care
    poate gresi, pentru o informatie pe care o avem sigura.
    """
    sursa_curata = (sursa or "").strip().lower()

    if sursa_curata not in SURSE_CUNOSCUTE:
        return {
            "ok": False,
            "motiv": f"sursa '{sursa}' nu are parser de pagina "
                     f"(stim: {', '.join(SURSE_CUNOSCUTE)})",
        }

    if not html or not html.strip():
        return {"ok": False, "motiv": "pagina e goala"}

    if sursa_curata == "ejobs":
        return extrage_din_ejobs(html)
    return extrage_din_bestjobs(html)


def extrage_din_ejobs(html: str) -> dict:
    """
    Descrierea dintr-o pagina eJobs, din blocul schema.org (application/ld+json).

    Pagina are un singur bloc ld+json, cu un "@graph" - o lista de noduri (WebSite,
    Organization, BreadcrumbList... si JobPosting). Il cautam pe cel cu @type
    "JobPosting" si ii luam `description`.

    Umblam prin TOATE blocurile ld+json de pe pagina, nu doar primul: azi e unul singur,
    dar daca maine site-ul mai adauga unul inainte, cautarea tot il gaseste pe cel bun.
    Gasirea nodului sta in _nod_jobposting_din_pagina, ca sa n-o repetam si la firma.
    """
    nod = _nod_jobposting_din_pagina(html)
    if not isinstance(nod, dict):
        return {"ok": False, "motiv": nod}

    descriere = nod.get("description")
    if not isinstance(descriere, str) or not descriere.strip():
        return {"ok": False, "motiv": "nodul JobPosting nu are camp `description`"}

    return _pregateste(descriere)


def extrage_din_bestjobs(html: str) -> dict:
    """
    Descrierea dintr-o pagina BestJobs, din incarcatura Next.js (__NEXT_DATA__).

    Drumul e props.pageProps.job.description. Il parcurgem cheie cu cheie si spunem
    exact unde s-a rupt, daca se rupe: "lipseste props.pageProps.job" e un motiv din
    care poti repara ceva, "n-a mers" nu e. Parcurgerea sta in _nod_job_din_next_data,
    ca sa n-o repetam si la firma.
    """
    nod = _nod_job_din_next_data(html)
    if not isinstance(nod, dict):
        return {"ok": False, "motiv": nod}

    descriere = nod.get("description")
    if not isinstance(descriere, str) or not descriere.strip():
        return {"ok": False, "motiv": "anuntul BestJobs nu are camp `description`"}

    return _pregateste(descriere)


def extrage_firma_si_titlul(html: str, sursa: str) -> dict:
    """
    Numele firmei si titlul adevarat, din aceleasi date structurate ca descrierea.

    Intoarce:
        {"ok": True,  "firma": "...", "titlu": "..."}   ambele gasite si negoale
        {"ok": False, "motiv": "..."}                   nu s-a putut, cu motivul exact

    DE CE E NEVOIE: din mailurile BestJobs de la sablonul 2026, firma nu se poate afla -
    e o poza fara text -, iar titlul vine cu mobilierul cardului lipit de el. Pe pagina,
    amandoua stau scrise separat, in acelasi bloc de date pe care il citim deja pentru
    descriere: __NEXT_DATA__ la BestJobs, schema.org la eJobs.

    PARTIAL SE RESPINGE, nu se completeaza pe jumatate - aceeasi regula ca la validarea
    raspunsurilor de model. Ambele campuri exista in structura la amandoua sursele; daca
    unul lipseste, structura nu e cea pe care o credem, si atunci nici celalalt nu e de
    incredere. Un motiv scris se repara; un camp umplut pe jumatate nu se mai vede.
    """
    sursa_curata = (sursa or "").strip().lower()

    if sursa_curata not in SURSE_CUNOSCUTE:
        return {
            "ok": False,
            "motiv": f"sursa '{sursa}' nu are parser de pagina "
                     f"(stim: {', '.join(SURSE_CUNOSCUTE)})",
        }

    if not html or not html.strip():
        return {"ok": False, "motiv": "pagina e goala"}

    if sursa_curata == "ejobs":
        nod = _nod_jobposting_din_pagina(html)
        if isinstance(nod, dict):
            organizatie = nod.get("hiringOrganization")
            firma = organizatie.get("name") if isinstance(organizatie, dict) else None
            return _pereche(firma, nod.get("title"))
        return {"ok": False, "motiv": nod}

    nod = _nod_job_din_next_data(html)
    if isinstance(nod, dict):
        angajator = nod.get("employer")
        firma = angajator.get("employerName") if isinstance(angajator, dict) else None
        return _pereche(firma, nod.get("title"))
    return {"ok": False, "motiv": nod}


def salariul_din_pagina(html: str, sursa: str) -> str:
    """
    Salariul din datele structurate ale paginii, ca text de filtru ("4000 - 5000 RON").
    Sir gol cand pagina nu-l spune.

    Doar eJobs: nodul JobPosting are, la unele anunturi, `baseSalary` cu moneda si
    capetele intervalului - scrise de angajator (14 din 46 de pagini, la 29 sept. 2026).
    BestJobs are doar `estimatedSalary`, o estimare a platformei, in EUR, pusa tocmai
    cand angajatorul si-a ascuns salariul - nu e salariul oferit, deci nu se ia.

    Net sau brut, JSON-ul nu spune; pagina eJobs scrie "RON net" langa cifre (13 din 14).
    Pragul din criterii e net, deci se compara direct.

    Se ia doar salariul lunar: fara `unitText` (cum vin toate azi) sau cu "MONTH". Alta
    unitate da sir gol - nu stim s-o comparam, iar filtrul o raporteaza ca salariu lipsa.
    Textul poarta "(din pagina)", ca in motive sa se vada de unde vine cifra.
    """
    if (sursa or "").strip().lower() != "ejobs":
        return ""

    nod = _nod_jobposting_din_pagina(html or "")
    if not isinstance(nod, dict):
        return ""

    salariu = nod.get("baseSalary")
    if not isinstance(salariu, dict):
        return ""
    moneda = salariu.get("currency")
    valoare = salariu.get("value")
    if not isinstance(moneda, str) or not moneda.strip() or not isinstance(valoare, dict):
        return ""
    if (valoare.get("unitText") or "MONTH").upper() != "MONTH":
        return ""

    # Intervalul, daca pagina il are; altfel valoarea unica. Nu amandoua: pe 30 sept. 2026,
    # 2 pagini aveau min = max = value = 3500 si ieseau "3500 - 3500 - 3500".
    capete = [_suma_intreaga(valoare.get(cheie)) for cheie in ("minValue", "maxValue")]
    capete = [capat for capat in capete if capat]
    if not capete:
        capete = [capat for capat in [_suma_intreaga(valoare.get("value"))] if capat]
    if not capete:
        return ""
    if len(capete) == 2 and capete[0] == capete[1]:
        capete = capete[:1]

    return f"{' - '.join(capete)} {moneda.strip()} (din pagina)"


def _suma_intreaga(valoare) -> str:
    """
    O suma din JSON ca text de cifre: 4000, "4000", 4000.0 si "4000.0" dau toate "4000".

    Sir gol pentru orice altceva - text, zecimale adevarate (4000.5), negativ. Nu ghicim:
    o suma cu bani marunti intr-un salariu lunar inseamna ca n-am inteles campul.
    """
    if isinstance(valoare, bool):
        return ""
    text = str(valoare if valoare is not None else "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text if text.isdigit() else ""


# Cum scrie fiecare pagina Romania, adusa la codul din criterii.yaml (tara_firma.permis).
_ROMANIA = {"ro", "romania", "românia", "rou"}


def tarile_din_pagina(html: str, sursa: str) -> list:
    """
    Tarile LOCULUI DE MUNCA din datele structurate ale paginii. Lista goala = pagina nu spune.

    Nu e tara firmei: aceea nu apare in date. Ce spun
    paginile:
      eJobs    applicantLocationRequirements.name ("Romania") - unde trebuie sa locuiesti;
               cand lipseste, JobPosting.jobLocation[].address.addressCountry ("RO").
      BestJobs doar `seoIsAbroad`, adevarat cand jobul e in strainatate; nu spune unde.
    Romania iese "RO", ca in criterii; orice alta tara iese asa cum e scrisa, iar un
    `seoIsAbroad` adevarat iese "strainatate". Fara sortare pe gust: ordinea e alfabetica.
    """
    sursa_curata = (sursa or "").strip().lower()
    tari = set()

    if sursa_curata == "ejobs":
        nod = _nod_jobposting_din_pagina(html or "")
        if not isinstance(nod, dict):
            return []
        # Rezidenta ceruta candidatului, cand pagina o spune, DECIDE singura: e raspunsul
        # direct la "de unde poti lucra". Adresa din jobLocation poate fi sediul unei firme
        # din Germania care angajeaza remote din Romania - luata si ea, respingea exact
        # rolurile remote cautate. Adresa conteaza doar cand rezidenta lipseste.
        tari = _tarile_rezidentei(nod) or _tarile_adresei(nod)

    elif sursa_curata == "bestjobs":
        nod = _nod_job_din_next_data(html or "")
        if isinstance(nod, dict) and nod.get("seoIsAbroad") is True:
            tari.add("strainatate")

    curate = set()
    for tara in tari:
        if isinstance(tara, str) and tara.strip():
            text = tara.strip()
            curate.add("RO" if text.lower() in _ROMANIA else text)
    return sorted(curate)


def _tarile_rezidentei(nod: dict) -> set:
    """Tarile din applicantLocationRequirements (unde trebuie sa locuiesti). Set gol = nespus."""
    cerinte = nod.get("applicantLocationRequirements")
    tari = set()
    for cerinta in cerinte if isinstance(cerinte, list) else [cerinte]:
        if isinstance(cerinta, dict) and isinstance(cerinta.get("name"), str):
            if cerinta["name"].strip():
                tari.add(cerinta["name"])
    return tari


def _tarile_adresei(nod: dict) -> set:
    """Tarile din jobLocation[].address.addressCountry. Set gol = nespus."""
    locuri = nod.get("jobLocation")
    tari = set()
    for loc in locuri if isinstance(locuri, list) else [locuri]:
        adresa = loc.get("address") if isinstance(loc, dict) else None
        if not isinstance(adresa, dict):
            continue
        tara = adresa.get("addressCountry")
        # schema.org permite si forma {"@type": "Country", "name": "RO"}, nu doar textul.
        if isinstance(tara, dict):
            tara = tara.get("name")
        if isinstance(tara, str) and tara.strip():
            tari.add(tara)
    return tari


def titlul_de_pastrat(titlu_din_mail: str, titlu_din_pagina: str) -> str:
    """
    Care titlu ramane, cand mailul si pagina spun lucruri diferite. Gol = se pastreaza mailul.

    REGULA, si e singura: pagina castiga DOAR cand titlul din mail e chiar titlul din
    pagina, plus ceva lipit la coada. Atat si nimic mai mult.

        mail:   "Multilingual HRBP (Business Partner) MIND AUTOMOBILE PART ROMANIA SRL"
        pagina: "Multilingual HRBP (Business Partner)"
        -> pagina, fiindca mailul o contine de la inceput si continua cu altceva

        mail:   "HR Generalist"
        pagina: "Specialist Resurse Umane"        (pagina in alta limba)
        -> gol: nu stim care e mai bun, deci nu atingem nimic

    DE CE atat de strict: `titlu` e data BRUTA, citita din mail. A o rescrie cu altceva
    e exact operatiunea pe care regulile proiectului o interzic, cu un singur temei
    acceptabil - ca ce era acolo sa fie DEMONSTRABIL acelasi lucru plus zgomot. Un
    "seamana destul de bine" ar fi inceputul rescrierii datelor dupa ureche.

    Comparam pe litere mici si cu spatiile stranse, ca doua spatii sau o majuscula sa nu
    strice potrivirea.
    """
    din_mail = " ".join((titlu_din_mail or "").split())
    din_pagina = " ".join((titlu_din_pagina or "").split())

    if not din_mail or not din_pagina:
        return ""
    if len(din_pagina) >= len(din_mail):
        return ""
    if din_mail.lower().startswith(din_pagina.lower()):
        return din_pagina
    return ""


# --- ajutoare pure -----------------------------------------------------------

def _pereche(firma, titlu) -> dict:
    """Perechea firma+titlu, acceptata doar intreaga. Vezi extrage_firma_si_titlul."""
    firma_curata = firma.strip() if isinstance(firma, str) else ""
    titlu_curat = titlu.strip() if isinstance(titlu, str) else ""

    lipsa = [
        nume
        for nume, valoare in (("firma", firma_curata), ("titlu", titlu_curat))
        if not valoare
    ]
    if lipsa:
        return {
            "ok": False,
            "motiv": f"pagina nu spune: {', '.join(lipsa)}",
        }

    return {"ok": True, "firma": firma_curata, "titlu": titlu_curat}


def _nod_jobposting_din_pagina(html: str):
    """
    Nodul JobPosting din ld+json-ul unei pagini eJobs, sau un motiv (text) daca nu exista.

    Intoarce dict sau str, ca sa poata fi folosit si de descriere, si de firma+titlu,
    fara ca vreuna sa repete cautarea prin blocuri.
    """
    blocuri = _blocuri_ld_json(html)
    if not blocuri:
        return "pagina nu contine niciun bloc application/ld+json"

    stricate = 0
    for bloc in blocuri:
        try:
            date = json.loads(bloc)
        except ValueError:
            stricate += 1
            continue

        nod = _cauta_jobposting(date)
        if nod is not None:
            return nod

    if stricate == len(blocuri):
        return "blocurile ld+json de pe pagina nu sunt JSON valid"
    return "in ld+json nu exista niciun nod @type JobPosting"


def _nod_job_din_next_data(html: str):
    """
    Nodul props.pageProps.job dintr-o pagina BestJobs, sau un motiv (text) daca nu exista.

    Spune exact unde s-a rupt drumul: "lipseste props.pageProps.job (rupt la 'job')" e un
    motiv din care poti repara ceva; "n-a mers" nu e.
    """
    bloc = _bloc_next_data(html)
    if bloc is None:
        return "pagina nu contine blocul __NEXT_DATA__"

    try:
        date = json.loads(bloc)
    except ValueError as eroare:
        return f"__NEXT_DATA__ nu e JSON valid: {eroare}"

    nod = date
    for cheie in ("props", "pageProps", "job"):
        if not isinstance(nod, dict) or cheie not in nod:
            return f"in __NEXT_DATA__ lipseste calea props.pageProps.job (rupt la '{cheie}')"
        nod = nod[cheie]

    if not isinstance(nod, dict):
        return "props.pageProps.job nu e un obiect cu campuri"
    return nod



def _pregateste(descriere_html: str) -> dict:
    """HTML-ul descrierii, ca text. Gol dupa curatare = esec, nu descriere vida."""
    text = _html_in_text(descriere_html)
    if not text:
        return {"ok": False, "motiv": "descrierea e goala dupa curatarea de HTML"}
    return {"ok": True, "descriere": text}


def _blocuri_ld_json(html: str) -> list:
    """Continutul fiecarui <script type="application/ld+json"> de pe pagina."""
    tipar = re.compile(
        r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )
    return [gasit.group(1).strip() for gasit in tipar.finditer(html)]


def _bloc_next_data(html: str):
    """Continutul lui <script id="__NEXT_DATA__">, sau None daca nu exista."""
    gasit = re.search(
        r"<script[^>]*id\s*=\s*[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return gasit.group(1).strip() if gasit else None


def _cauta_jobposting(date):
    """
    Nodul cu @type "JobPosting", oriunde ar sta in structura ld+json.

    De ce cautam in adancime in loc sa mergem pe "@graph": forma difera de la site la
    site - unele pun un obiect singur, altele o lista, altele un "@graph". Cautarea
    recursiva le acopera pe toate si nu se strica daca eJobs isi rearanjeaza blocul.

    `@type` poate fi si o LISTA de tipuri (schema.org permite) - de aia verificam si
    cazul ala, nu doar sirul simplu.
    """
    if isinstance(date, dict):
        tip = date.get("@type")
        tipuri = tip if isinstance(tip, list) else [tip]
        if any(str(t).lower() == "jobposting" for t in tipuri if t):
            return date
        for valoare in date.values():
            gasit = _cauta_jobposting(valoare)
            if gasit is not None:
                return gasit
    elif isinstance(date, list):
        for element in date:
            gasit = _cauta_jobposting(element)
            if gasit is not None:
                return gasit
    return None


class _TextDinHTML(HTMLParser):
    """
    Scoate textul dintr-un fragment de HTML, pastrand ruperile de rand.

    Nu folosim `curata_textul` din parse/comun.py, care lipeste tot pe un singur rand:
    acolo se citea un TITLU dintr-un card de mail, aici o descriere de 2000 de caractere
    cu responsabilitati si cerinte. Un perete de text fara randuri e mai greu de citit
    si pentru om, si pentru model.

    `convert_charrefs` e implicit True, deci entitatile (&amp;, &#8211;) ajung in
    handle_data deja transformate in caractere. Nu mai trebuie desfacute separat.
    """

    def __init__(self):
        super().__init__()
        self.bucati = []

    def handle_starttag(self, eticheta, atribute):
        if eticheta in ETICHETE_DE_RUPERE:
            self.bucati.append("\n")

    def handle_endtag(self, eticheta):
        if eticheta in ETICHETE_DE_RUPERE:
            self.bucati.append("\n")

    def handle_data(self, text):
        self.bucati.append(text)


def _html_in_text(fragment: str) -> str:
    """
    Un fragment de HTML, ca text citibil: fara etichete, cu randuri pastrate.

    Trei curatari, in ordine:
      1. etichetele dispar, iar cele "de bloc" lasa in urma o rupere de rand;
      2. spatiile din capatul fiecarui rand se taie (HTML-ul e plin de indentare);
      3. randurile goale in sir se string la cel mult unul - altfel o descriere cu
         <p></p> peste tot ar iesi cu zece randuri albe intre paragrafe.
    """
    cititor = _TextDinHTML()
    cititor.feed(fragment)
    brut = "".join(cititor.bucati)

    # \xa0 e spatiul care nu rupe randul; in text obisnuit n-are ce cauta.
    randuri = [rand.replace("\xa0", " ").strip() for rand in brut.split("\n")]

    curatate = []
    for rand in randuri:
        if rand or (curatate and curatate[-1]):
            curatate.append(rand)

    return "\n".join(curatate).strip()
