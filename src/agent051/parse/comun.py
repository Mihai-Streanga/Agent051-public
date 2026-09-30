"""
Unelte comune tuturor parserelor.

Ce e un parser, in cuvinte simple: un mail de la eJobs contine zece anunturi.
Parserul il sparge in zece bucati, fiecare cu titlu, firma si link propriu.
E o operatiune DETERMINISTA - aceleasi date de intrare dau mereu acelasi rezultat.
Niciun AI nu are ce cauta aici: nu e nimic de judecat, e doar de citit o structura.

REGULA CENTRALA A TUTUROR PARSERELOR: ESUEAZA ZGOMOTOS, NU GHICI.
Daca structura mailului nu arata cum ne asteptam, parserul RIDICA O EROARE.
Nu intoarce o lista goala si nu se preface ca a mers. Un parser care extrage
0 anunturi din 50 de mesaje si raporteaza "succes" e mai rau decat unul care crapa:
te lasa sa crezi ca n-au fost joburi, cand de fapt sablonul s-a schimbat.

Toate functiile de aici sunt PURE: primesc text, intorc date. Fara retea, fara disc.
"""

import base64
import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse


class EroareParser(Exception):
    """
    Un mesaj nu a putut fi spart in anunturi.

    Poarta cu ea sursa si id-ul mesajului, ca sa stii EXACT care mail a stricat-o.
    Fara astea, un raport de eroare e inutil: nu ai cum sa te uiti la mailul vinovat.
    """

    def __init__(self, sursa: str, mesaj_id: str, motiv: str):
        self.sursa = sursa
        self.mesaj_id = mesaj_id
        self.motiv = motiv
        super().__init__(f"[{sursa}] mesajul {mesaj_id}: {motiv}")


class _CititorHTML(HTMLParser):
    """
    Transforma HTML-ul intr-un sir de elemente simple, in ordinea in care apar:

        ("link", href, textul_din_link)
        ("text", "", textul_liber)

    DE CE asa: intr-un mail, informatia despre un job e imprastiata. Titlul e intr-un
    link, firma e uneori in alt link, alteori doar text alaturi. Daca pastram ORDINEA
    in care apar, putem spune "firma e textul care urmeaza dupa titlu" - ceea ce e
    exact felul in care citeste un om mailul, de sus in jos.

    Sarim peste script si style: nu sunt continut, sunt cod si culori.
    """

    ETICHETE_DE_IGNORAT = {"script", "style", "head", "title"}

    def __init__(self, pastreaza_marginile: bool = False):
        super().__init__()  # convert_charrefs=True traduce singur &amp; -> &
        self.elemente = []
        # Pozitia fiecarui link din `elemente` -> bucatile de text din el, separat. Vezi
        # elemente_si_bucatile_linkurilor: un card intreg poate sta intr-un singur link.
        self.bucatile_linkurilor = {}
        self._pastreaza_marginile = pastreaza_marginile
        self._in_zona_ignorata = 0
        self._href_curent = None
        self._text_link = []

    def handle_starttag(self, tag, attrs):
        if tag in self.ETICHETE_DE_IGNORAT:
            self._in_zona_ignorata += 1
        elif tag == "a":
            # Un <a> deschis inainte ca altul sa se inchida (HTML stricat, se intampla
            # des in mailuri): inchidem ce aveam, ca sa nu pierdem textul strans.
            self._inchide_linkul()
            self._href_curent = dict(attrs).get("href", "")
            self._text_link = []

    def handle_endtag(self, tag):
        if tag in self.ETICHETE_DE_IGNORAT and self._in_zona_ignorata > 0:
            self._in_zona_ignorata -= 1
        elif tag == "a":
            self._inchide_linkul()

    def handle_data(self, data):
        if self._in_zona_ignorata:
            return
        if self._href_curent is not None:
            self._text_link.append(data)
        else:
            curat = _text_liber(data, self._pastreaza_marginile)
            if curat:
                self.elemente.append(("text", "", curat))

    def _inchide_linkul(self):
        if self._href_curent is None:
            return
        self.bucatile_linkurilor[len(self.elemente)] = [
            curat for curat in (curata_textul(bucata) for bucata in self._text_link) if curat
        ]
        self.elemente.append(
            ("link", self._href_curent, curata_textul("".join(self._text_link)))
        )
        self._href_curent = None
        self._text_link = []

    def close(self):
        super().close()
        self._inchide_linkul()


def curata_textul(text: str) -> str:
    """Un singur rand, fara spatii de prisos. \\xa0 e spatiul din HTML care nu rupe randul."""
    if not text:
        return ""
    return " ".join(text.replace("\xa0", " ").split())


def _text_liber(data: str, pastreaza_marginile: bool) -> str:
    """
    Un text liber, pregatit pentru lista de elemente. Gol daca era doar spatiu.

    `pastreaza_marginile` schimba un singur lucru: daca spatiul de la CAPETELE textului
    supravietuieste. In mod normal nu conteaza si il taiem, ca peste tot.

    Conteaza intr-un singur caz, si de-acolo vine intreaga optiune: cand un nume e RUPT
    in mai multe texte de catre marcajul mailului, iar parserul trebuie sa-l lipeasca la
    loc. eJobs scrie asa:
        S<span>.</span>C<span>.</span> HATTRICK BET S<span>.</span>R<span>.</span>L
    adica pune punctele in etichete separate (probabil ca sa nu i le transforme in
    link-uri programele de mail). Textul ajunge la noi in zece bucati. Lipite fara
    margini, ies " JUMBO EC" + "." + "R" + "." + " SRL" = "JUMBO EC.R.SRL" - fara spatiul
    dinaintea lui SRL, care exista in mail. Adica un nume de firma gresit, scris de noi.

    Nu e comportamentul implicit fiindca celelalte parsere se sprijina pe textul deja
    curatat - parserul LinkedIn, de pilda, potriveste "3 contacte" cu o expresie ancorata
    la inceputul sirului, iar un spatiu in fata ar face-o sa nu mai potriveasca nimic.
    Cine are nevoie de margini le cere; pentru toti ceilalti nu se schimba nimic.
    """
    if not pastreaza_marginile:
        return curata_textul(data)

    colapsat = re.sub(r"\s+", " ", data.replace("\xa0", " "))
    # Un text din doar spatii nu e continut - ar deveni un element gol care incurca
    # numaratoarea "primul text de dupa titlu".
    return colapsat if colapsat.strip() else ""


def elemente_din_html(html: str, pastreaza_marginile: bool = False) -> list:
    """
    Sirul de link-uri si texte, in ordinea din pagina. Vezi _CititorHTML.

    `pastreaza_marginile` e explicat pe larg in _text_liber: il cere doar parserul eJobs,
    care trebuie sa lipeasca la loc nume de firma rupte de marcaj. Implicit, nimic nu se
    schimba fata de inainte.
    """
    return elemente_si_bucatile_linkurilor(html, pastreaza_marginile)[0]


def elemente_si_bucatile_linkurilor(html: str, pastreaza_marginile: bool = False) -> tuple:
    """
    Ca elemente_din_html, plus, pentru fiecare link, bucatile lui de text, separat.

    Intoarce (elemente, bucati), unde bucati[pozitie] e lista textelor din link-ul aflat
    la `pozitie` in elemente, in ordine, fara cele goale.

    DE CE: in textul unui link, bucatile se lipesc intr-un singur rand. De obicei link-ul
    tine doar titlul, deci nu conteaza. Dar LinkedIn pune uneori TOT cardul jobului intr-un
    link - titlul intr-o celula, "Firma · Oras" in alta -, iar lipite ies un titlu care
    contine si firma, si orasul. Cu bucatile separate, parserul le poate desparti.
    """
    cititor = _CititorHTML(pastreaza_marginile)
    try:
        cititor.feed(html)
        cititor.close()
    except Exception:
        # HTML stricat: pastram ce s-a apucat sa citeasca. Daca a citit prea putin,
        # parserul sursei va observa ca n-a gasit anunturi si va TIPA oricum.
        pass
    return cititor.elemente, cititor.bucatile_linkurilor


def desfa_redirectul(href: str) -> str:
    """
    Din link-ul de urmarire, scoate URL-ul adevarat al anuntului.

    Platformele nu pun in mail link-ul direct catre job. Pun un link catre serverul
    lor de statistici, care numara clicul si abia apoi te trimite mai departe.
    URL-ul real e ascuns INAUNTRUL acestui link, in doua feluri:

    1. eJobs (dupa 2022):
       http://cb.mta.ejobs.ro/erdr/<id>-<id>-1-0-aHR0cHM6Ly93d3cuZWpvYnMucm8v...
       Ultima bucata e URL-ul real, codificat base64. "aHR0cHM6" inseamna "https:".

    2. BestJobs:
       http://news.bestjobs.eu/click/123/456/zppi/abc/?u=https%3A%2F%2Fwww.bestjobs.eu%2F...
       URL-ul real e in parametrul "u", cu caracterele speciale codificate.

    DE CE ne chinuim sa-l desfacem, in loc sa pastram link-ul de urmarire:
    link-ul de urmarire e UNIC PER MAIL. Acelasi job, trimis in doua mailuri diferite,
    ar avea doua link-uri de urmarire diferite - si ar intra de doua ori in baza,
    ca doua oportunitati distincte. URL-ul real e stabil: acelasi job = acelasi link,
    mereu. Pe el se sprijina identificarea anunturilor.

    Daca nu e un link de urmarire cunoscut, il intoarcem neschimbat.
    """
    if not href:
        return ""

    adresa = href.replace("&amp;", "&").strip()

    # Cazul BestJobs: URL-ul real sta in parametrul "u".
    intrebari = parse_qs(urlparse(adresa).query)
    if "u" in intrebari and intrebari["u"]:
        candidat = unquote(intrebari["u"][0])
        if candidat.startswith("http"):
            return candidat

    # Cazul eJobs: coada caii e URL-ul in base64.
    if "/erdr/" in adresa:
        cale = urlparse(adresa).path
        # Calea arata asa: /erdr/<id>-<id>-1-0-<base64>. Base64-ul e cel standard, care
        # poate contine "/" - deci se ia TOT ce urmeaza dupa a patra liniuta, nu doar
        # ultimul segment al caii. Cu ultimul segment, un base64 cu "/" in el iesea rupt
        # si nedecodabil, iar joburile din mail se pierdeau (doua mailuri "Căutari
        # salvate", gasite pe 30 sept. 2026). Formele vechi raman ca rezerva.
        dupa_erdr = cale.split("/erdr/", 1)[1]
        ultimul_segment = cale.rstrip("/").split("/")[-1]
        for bucata in (
            dupa_erdr.split("-", 4)[-1],
            ultimul_segment.split("-")[-1],
            ultimul_segment,
        ):
            decodat = _incearca_base64(bucata)
            if decodat:
                return decodat

    return adresa


def _incearca_base64(text: str):
    """Decodeaza base64 daca rezultatul e un URL. Altfel, None. Nu arunca erori."""
    if not text or len(text) < 8:
        return None
    try:
        # base64 cere lungimea multiplu de 4; link-urile vin adesea fara umplutura.
        umplut = text + "=" * (-len(text) % 4)
        rezultat = base64.b64decode(umplut).decode("utf-8", errors="replace")
    except Exception:
        return None
    return rezultat if rezultat.startswith("http") else None


def fara_parametri(url: str) -> str:
    """
    Taie coada de urmarire (?utm_source=...) si pastreaza doar adresa curata.

    Acelasi job, in doua mailuri, vine cu utm_campaign diferit. Fara taierea asta,
    ar arata ca doua joburi diferite. Identitatea unui anunt sta in adresa, nu in
    eticheta de marketing lipita la coada.
    """
    if not url:
        return ""
    bucati = urlparse(url)
    return f"{bucati.scheme}://{bucati.netloc}{bucati.path}".rstrip("/")


def amprenta(text: str) -> str:
    """
    Un identificator scurt si stabil, calculat din text.

    Acelasi text da mereu aceeasi amprenta. Asta face ca acelasi anunt, intalnit in
    doua mesaje diferite, sa primeasca acelasi id - si sa intre o singura data in baza.
    """
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:20]


# Texte de navigatie care apar in link-uri, dar NU sunt titluri de job.
# Le tinem intr-un singur loc, ca sa nu fie imprastiate prin trei parsere.
TEXTE_DE_NAVIGATIE = {
    "vezi toate joburile", "vezi jobul", "see all jobs", "update cv",
    "incepe interviul", "începe interviul", "& altele", "si altele", "și altele",
    "setari alerte", "setări alerte", "dezabonare", "dezabonați-vă", "dezabonati-va",
    "aplica", "aplică", "apply", "vizualizați jobul", "vizualizati jobul",
    "vizualizați toate joburile", "vizualizati toate joburile",
    "vizualizați mai multe joburi", "gestionați alertele", "administrați alertele de job",
    "asistență", "asistenta", "actualizați-vă profilul", "căutați joburi",
    "încercați premium pentru 0 lei", "aflați de ce am inclus aceasta.",
    "actualizeaza-ti cv-ul", "cauta joburi",
}


def e_text_de_navigatie(text: str) -> bool:
    """Textul asta e un buton/meniu, nu un titlu de job?"""
    return curata_textul(text).lower() in TEXTE_DE_NAVIGATIE


def anunt(
    sursa: str,
    titlu: str,
    firma: str,
    locatie: str,
    link: str,
    cheie: str,
    descriere: str = "",
    salariu_brut: str = "",
) -> dict:
    """
    Construieste un anunt, in forma in care intra in baza de date.

    `cheie` e ce identifica anuntul in mod unic (de obicei URL-ul curat). Din ea
    calculam id-ul. Daca lipseste, folosim titlul + firma - mai slab, dar mai bine
    decat nimic. Vezi comentariul despre id in store/db.py.

    descriere si salariu_brut sunt OPTIONALE si adesea goale: nu toate anunturile din
    mailurile de alerta au un fragment de descriere sau un salariu afisat. Un camp gol
    NU e o eroare - vezi regula parserelor. `cheie` NU le include: un anunt trebuie sa
    aiba acelasi id fie ca a fost prins cu salariu, fie fara, altfel acelasi job ar
    intra de doua ori.
    """
    baza_id = cheie or f"{titlu}|{firma}"
    return {
        "id": amprenta(baza_id),
        "sursa": sursa,
        "titlu": curata_textul(titlu),
        "firma": curata_textul(firma),
        "locatie": curata_textul(locatie),
        "link": link,
        "descriere": curata_textul(descriere),
        "salariu_brut": curata_textul(salariu_brut),
    }


# Un text de salariu are cifre lipite de o moneda sau unitate: "1600 - 1900€",
# "805 - 890 € (Estimare salariala)", "2500 RON". Pastram valuta in text (nu o
# aruncam): filtrul are nevoie de ea ca sa stie daca poate compara cu un prag in RON.
TIPAR_SALARIU = re.compile(r"\d[\d.,\s]*(RON|lei|€|EUR|\$|USD)", re.IGNORECASE)


def imparte_salariu_descriere(texte: list) -> tuple:
    """
    Din textele libere de sub un titlu, separa salariul de restul (descrierea).

    In mailurile de alerta nu exista proza de descriere per anunt - sunt carduri
    compacte. Ce apare sub titlu sunt fragmente scurte: salariul, felul muncii
    ("Job remote"), orasul, beneficiile ("Bonus de performanta"). Le impartim asa:

      salariu_brut - PRIMUL fragment care arata a salariu (cifre + moneda), pastrat
                     EXACT, doar fara "/"-ul decorativ din fata. Interpretarea ("e sub
                     prag? in ce valuta?") NU se face aici - se face in filtru, pe text.
      descriere    - restul fragmentelor, lipite intr-un singur sir. Nu e o descriere
                     adevarata, e "tot ce a mai ramas de citit sub titlu" - si exact
                     acolo cauta filtrul cuvinte ca "ture" sau "night shift", care nu
                     apar in titlu.

    Un separator singur ("/") nu e nici salariu, nici descriere - se arunca.
    Amandoua pot iesi goale, si e in regula: nu orice anunt are salariu sau descriere.
    """
    salariu = ""
    restul = []
    for text in texte:
        curat = curata_textul(text)
        if not curat or curat == "/":
            continue
        if not salariu and TIPAR_SALARIU.search(curat):
            # Taiem "/"-ul si spatiile decorative din fata ("/ 1600 - 1900€").
            salariu = curat.lstrip("/ ").strip()
        else:
            restul.append(curat)
    return salariu, " ".join(restul)
