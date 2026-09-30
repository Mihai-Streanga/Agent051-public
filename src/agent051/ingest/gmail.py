"""
Conexiunea la Gmail prin IMAP: verificare si citire.

IMAP e protocolul prin care un program citeste o cutie postala de pe un server,
fara sa mute mailurile de acolo. E acelasi lucru pe care il face Thunderbird sau
aplicatia de mail de pe telefon.

REGULA ABSOLUTA a acestui fisier: NU MODIFICA NIMIC IN GMAIL.
Nu sterge, nu muta, nu marcheaza nimic ca citit. Doar priveste. Vezi
comentariile despre `readonly=True` si `BODY.PEEK` - acolo se tine promisiunea.

Locul lui in arhitectura: `ingest/` = tot ce atinge lumea din afara (reteaua).
Aici e permis I/O. Logica de business (evaluarea joburilor) sta in `core/`,
ca functii pure, si nu are voie sa stie ca IMAP exista.
"""

import base64
import email
import email.header
import email.utils
import hashlib
import imaplib
import os
import re
import socket
import ssl
from html.parser import HTMLParser
from pathlib import Path

from dotenv import load_dotenv

# Adresa serverului IMAP al Gmail. Portul 993 = IMAP peste SSL,
# adica traficul e criptat de la inceput pana la sfarsit.
SERVER_GMAIL = "imap.gmail.com"
PORT_IMAP_SSL = 993

# Daca serverul nu raspunde in atatea secunde, renuntam.
# Fara asta, un internet cazut ar lasa programul sa astepte la nesfarsit.
TIMEOUT_SECUNDE = 15

# Radacina proiectului: urcam trei niveluri de la fisierul asta
# (ingest -> agent051 -> src -> radacina). Acolo sta fisierul .env.
RADACINA_PROIECT = Path(__file__).resolve().parents[3]

# Din ce domeniu de mail vine anuntul. Lista e deliberat scurta si explicita:
# daca maine apare o sursa noua, se adauga aici o linie, nu se rescrie cod.
SURSE_CUNOSCUTE = {
    "ejobs.ro": "ejobs",
    "bestjobs.eu": "bestjobs",
    "bestjobs.ro": "bestjobs",
    "linkedin.com": "linkedin",
    "hipo.ro": "hipo",
    "indeed.com": "indeed",
}


# =============================================================
# Functii pure - primesc date, intorc date. Nu ating reteaua.
# Se pot testa fara internet si fara cont de Gmail.
# =============================================================


def _codifica_nume_folder(nume: str) -> str:
    """
    Traduce numele unui folder Gmail in codificarea ceruta de IMAP.

    DE CE e nevoie de asta:
    IMAP e un protocol vechi (1996) si accepta in numele folderelor doar caractere
    ASCII simple. Un folder numit "Joburi" trece nemodificat. Dar unul cu diacritice
    - "Cautari" scris corect - sau cu simbolul "&" nu trece: serverul ar raspunde
    ca folderul nu exista, desi el exista.

    Regula (se numeste "modified UTF-7", din standardul IMAP):
      - caracterele ASCII normale raman asa cum sunt;
      - "&" devine "&-", pentru ca "&" e caracterul special care marcheaza inceputul
        unei secvente codificate, deci trebuie "scapat";
      - orice altceva (diacritice, emoji) se codifica in base64 si se pune intre
        "&" si "-". In plus, base64-ul standard foloseste "/", care in IMAP separa
        folderele imbricate, asa ca "/" se inlocuieste cu ",".
    """
    rezultat = []
    de_codificat = []  # caractere ne-ASCII acumulate, care se codifica impreuna

    def goleste_tamponul():
        """Codifica in base64 caracterele speciale stranse pana acum."""
        if not de_codificat:
            return
        text = "".join(de_codificat)
        # UTF-16BE e formatul cerut de standard inainte de base64.
        octeti = text.encode("utf-16-be")
        # "=" de la sfarsitul base64-ului nu se pune in IMAP, de aceea rstrip.
        b64 = base64.b64encode(octeti).decode("ascii").rstrip("=")
        rezultat.append("&" + b64.replace("/", ",") + "-")
        de_codificat.clear()

    for caracter in nume:
        if caracter == "&":
            goleste_tamponul()
            rezultat.append("&-")
        elif 0x20 <= ord(caracter) <= 0x7E:
            goleste_tamponul()
            rezultat.append(caracter)
        else:
            de_codificat.append(caracter)

    goleste_tamponul()
    return "".join(rezultat)


def _ascunde_parola(text: str, parola: str) -> str:
    """
    Plasa de siguranta: daca parola ar aparea vreodata intr-un mesaj de eroare
    venit de la biblioteca IMAP, o inlocuim cu asteriscuri inainte sa iasa afara.

    Nu ne asteptam sa se intample. Dar un mesaj de eroare ajunge in log-uri,
    in capturi de ecran, in conversatii - si de acolo nu-l mai poti retrage.
    """
    if parola and parola in text:
        return text.replace(parola, "***")
    return text


def _decodifica_antet(valoare_bruta) -> str:
    """
    Traduce un antet de mail (Subject, From) in text normal, citibil.

    DE CE e nevoie:
    Anteturile de mail au voie sa contina, prin standard, doar caractere ASCII.
    Un subiect cu diacritice sau cu emoji nu incape asa, deci se CODIFICA. Ajunge
    la noi aratand cam asa:
        =?UTF-8?B?Sm9idXJpIG5vaSBwZW50cnUgdGluZQ==?=
    Ce vede omul in Gmail e "Joburi noi pentru tine". Ce vine pe fir e sirul de mai
    sus. Fara traducerea asta, in baza de date ar ajunge mizeria, nu subiectul.

    Un singur antet poate amesteca mai multe bucati, fiecare in alta codificare
    (o parte ASCII, o parte UTF-8). De aceea le luam pe rand si le lipim la loc.
    """
    if not valoare_bruta:
        return ""

    bucati = []
    for continut, codificare in email.header.decode_header(valoare_bruta):
        if isinstance(continut, bytes):
            # errors="replace": daca un octet nu se poate traduce, punem un semn de
            # intrebare in locul lui. Un subiect ciudat nu are voie sa opreasca tot.
            bucati.append(continut.decode(codificare or "utf-8", errors="replace"))
        else:
            bucati.append(continut)

    # Anteturile pot contine rupturi de linie (mailurile lungi se "impacheteaza").
    # Le transformam in spatii, ca sa avem o singura linie curata.
    return " ".join("".join(bucati).split())


class _ExtragatorText(HTMLParser):
    """
    Scoate textul dintr-o pagina HTML.

    Mailurile de la LinkedIn sau eJobs sunt, de fapt, pagini web: tabele, culori,
    butoane, imagini. Noua nu ne trebuie decat textul. Clasa asta parcurge HTML-ul
    si strange doar ce ar citi un om cu ochii.

    Folosim html.parser, care vine cu Python. Fara biblioteci noi.
    """

    # Ce e INAUNTRUL acestor etichete nu e text pentru om - e cod si stiluri.
    # Daca nu le sarim, in baza de date ar ajunge JavaScript si reguli CSS.
    ETICHETE_DE_IGNORAT = {"script", "style", "head", "title"}

    # Etichete care, vizual, rup randul. Punem o linie noua ca textul sa nu se
    # lipeasca: "Contabil SeniorFirma X" in loc de doua randuri distincte.
    ETICHETE_BLOC = {
        "p", "div", "br", "tr", "td", "th", "li", "ul", "ol",
        "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article",
    }

    def __init__(self):
        # convert_charrefs=True (implicit) traduce singur &amp; in &, &nbsp; in spatiu.
        super().__init__()
        self._bucati = []
        self._in_zona_ignorata = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.ETICHETE_DE_IGNORAT:
            self._in_zona_ignorata += 1
        elif tag in self.ETICHETE_BLOC:
            self._bucati.append("\n")

    def handle_endtag(self, tag):
        if tag in self.ETICHETE_DE_IGNORAT and self._in_zona_ignorata > 0:
            self._in_zona_ignorata -= 1
        elif tag in self.ETICHETE_BLOC:
            self._bucati.append("\n")

    def handle_data(self, data):
        # Culegem text doar daca nu suntem intr-o zona ignorata (script/style).
        if self._in_zona_ignorata == 0:
            self._bucati.append(data)

    def text(self) -> str:
        return "".join(self._bucati)


def _curata_spatiile(text: str) -> str:
    """
    Face textul citibil: fara spatii de prisos, fara randuri goale in serie.

    Dintr-un HTML de mail ies zeci de linii goale si spatii duble. Le strangem,
    dar PASTRAM randurile: structura pe randuri e utila mai tarziu, cand vom
    separa joburile dintr-un mail care contine zece anunturi.
    """
    randuri = []
    for rand in text.splitlines():
        # \xa0 e "spatiul care nu rupe randul", foarte des in HTML. Arata ca un
        # spatiu, dar nu e acelasi caracter - si strica orice cautare de text.
        curat = " ".join(rand.replace("\xa0", " ").split())
        if curat:
            randuri.append(curat)
    return "\n".join(randuri)


def _html_in_text(html: str) -> str:
    """Din HTML brut, textul pe care l-ar citi un om."""
    extragator = _ExtragatorText()
    try:
        extragator.feed(html)
    except Exception:
        # Un HTML stricat (si mailurile au adesea HTML stricat) nu are voie sa
        # opreasca ingestia. Pastram ce s-a apucat sa culeaga pana la eroare.
        pass
    return _curata_spatiile(extragator.text())


def deduce_sursa(expeditor: str) -> str:
    """
    Din adresa expeditorului, deduce platforma: ejobs / bestjobs / linkedin / ...

    Determinist si transparent: cautam domeniul cunoscut in adresa. Fara AI - nu e
    nimic de judecat aici, e o simpla potrivire de text. AI-ul ar fi mai lent, mai
    scump, si ar putea da alt raspuns maine la aceeasi intrare.

    Ce nu recunoastem primeste "necunoscut". Nu ghicim si nu inventam: un mail cu
    sursa necunoscuta e vizibil in baza, si poti decide tu ce e cu el.
    """
    adresa = (expeditor or "").lower()
    for domeniu, nume in SURSE_CUNOSCUTE.items():
        if domeniu in adresa:
            return nume
    return "necunoscut"


def _extrage_corpul(mesaj: email.message.Message) -> tuple:
    """
    Scoate din mail AMBELE variante ale corpului: textul si HTML-ul brut.

    Intoarce (corp_text, corp_html).

    DE CE pastram si HTML-ul, desi textul e mai curat si mai usor de citit:
    link-urile unui anunt nu stau in text - stau in atributele href ale HTML-ului.
    Cand curatam HTML-ul, le aruncam. La prima ingestie asta s-a si intamplat, si
    a trebuit sa recitim toate cele 444 de mesaje ca sa le recuperam.
    Regula proiectului, invatata pe pielea noastra: INGESTIA PASTREAZA DATE BRUTE.
    Nu curata, nu simplifica, nu decide ce e util. Discul e ieftin; o re-ingestie
    e scumpa. Curatarea si interpretarea sunt etape separate, care lucreaza pe date
    deja salvate si se pot repeta oricand, fara sa atinga reteaua.

    Un mail e adesea trimis in DOUA variante deodata (se numeste "multipart"):
    una simpla, text curat, si una HTML, cu poze si culori. Le luam pe amandoua.
    Daca varianta text lipseste - la eJobs lipseste mereu - o fabricam noi din HTML,
    dar HTML-ul original ramane salvat, neatins.
    """
    parti_text = []
    parti_html = []

    # walk() parcurge toate "straturile" mailului, oricat de adanc ar fi imbricate.
    for parte in mesaj.walk():
        tip = parte.get_content_type()

        # Sarim atasamentele. Nu ne intereseaza si pot fi mari.
        dispozitie = str(parte.get("Content-Disposition") or "")
        if "attachment" in dispozitie.lower():
            continue

        if tip not in ("text/plain", "text/html"):
            continue

        # decode=True desface codificarea de transport (base64, quoted-printable)
        # si ne da octetii reali.
        octeti = parte.get_payload(decode=True)
        if not octeti:
            continue

        # Fiecare parte isi declara propria codificare de caractere. Daca nu o
        # declara, presupunem UTF-8 - cea mai probabila azi.
        codificare = parte.get_content_charset() or "utf-8"
        try:
            continut = octeti.decode(codificare, errors="replace")
        except LookupError:
            # Codificare exotica, pe care Python n-o cunoaste. Nu abandonam mailul.
            continut = octeti.decode("utf-8", errors="replace")

        if tip == "text/plain":
            parti_text.append(continut)
        else:
            parti_html.append(continut)

    # HTML-ul, exact cum a venit. Neatins, necuratat. E singurul loc unde traiesc
    # link-urile anunturilor.
    corp_html = "\n".join(parti_html)

    # Textul: il preferam pe cel trimis de expeditor (e deja curat). Daca lipseste,
    # il fabricam noi din HTML - dar HTML-ul de mai sus ramane salvat oricum.
    if parti_text:
        corp_text = _curata_spatiile("\n".join(parti_text))
    elif corp_html:
        corp_text = _html_in_text(corp_html)
    else:
        corp_text = ""

    return corp_text, corp_html


def _data_in_iso(valoare_bruta: str) -> str:
    """
    Traduce data mailului in format ISO 8601: 2026-07-13T09:15:00+03:00.

    In mail, data arata asa: "Mon, 13 Jul 2026 09:15:00 +0300". Formatul e citibil
    pentru om, dar prost pentru un calculator: nu se poate sorta ca text si nu se
    poate compara. ISO 8601 se sorteaza corect chiar si ca simplu sir de caractere -
    de asta il folosim in baza de date.
    """
    if not valoare_bruta:
        return ""
    try:
        momentul = email.utils.parsedate_to_datetime(valoare_bruta)
    except (TypeError, ValueError):
        # Antet Date stricat sau lipsa. Pastram valoarea bruta, ca sa nu pierdem
        # informatia - mai bine ceva imperfect decat nimic.
        return valoare_bruta
    if momentul is None:
        return valoare_bruta
    return momentul.isoformat()


TIPAR_UID = re.compile(rb"UID (\d+)")


def _identificatorii_din_raspuns(linii: list) -> list:
    """
    Din raspunsul brut al serverului la cererea de anteturi, perechile UID + Message-ID.

    Intoarce: [{"uid": "12", "id": "<abc@ejobs.ro>"}, ...]

    Serverul raspunde cu o insiruire de bucati care arata cam asa:
        (b'1 (UID 12 BODY[HEADER.FIELDS (MESSAGE-ID)] {45}', b'Message-ID: <abc@...>')
    adica o pereche: intai eticheta (in care sta UID-ul), apoi continutul cerut.
    Ce nu e pereche (paranteze de inchidere, raspunsuri fara continut) se sare.

    Un mesaj fara Message-ID iese cu "id" gol. NU il aruncam aici: functia asta doar
    citeste ce a spus serverul. Ce se face cu un mesaj fara identificator se decide in
    core/ingestie.py - si acolo decizia e sa i se aduca oricum corpul, fiindca abia
    din corp i se poate calcula o amprenta stabila.
    """
    identificatori = []

    for bucata in linii:
        if not isinstance(bucata, tuple) or len(bucata) < 2:
            continue

        eticheta, continut = bucata[0], bucata[1]
        if not isinstance(eticheta, bytes) or not isinstance(continut, bytes):
            continue

        potrivire = TIPAR_UID.search(eticheta)
        if not potrivire:
            continue

        antet = email.message_from_bytes(continut)
        # .strip() si nimic altceva - EXACT ca la citirea corpului intreg (vezi
        # _mail_din_octeti). Daca cele doua drumuri ar curata id-ul diferit, acelasi
        # mail ar primi doua id-uri diferite, s-ar descarca la fiecare rulare si
        # ar intra de doua ori in baza. Aceeasi regula, scrisa o data in fiecare loc.
        id_mail = (antet.get("Message-ID") or "").strip()

        identificatori.append(
            {"uid": potrivire.group(1).decode("ascii"), "id": id_mail}
        )

    return identificatori


def _mail_din_octeti(octeti: bytes) -> dict:
    """
    Dintr-un mail brut, asa cum vine de pe fir, dictionarul pe care il salvam in baza.

    Functie pura: primeste octeti, intoarce date. Nu atinge nici reteaua, nici discul.
    """
    mesaj = email.message_from_bytes(octeti)

    expeditor = _decodifica_antet(mesaj.get("From"))
    subiect = _decodifica_antet(mesaj.get("Subject"))
    data_primire = _data_in_iso(mesaj.get("Date"))
    corp_text, corp_html = _extrage_corpul(mesaj)

    # Message-ID: identificatorul unic al mailului, emis de serverul care l-a trimis.
    # E cheia pe care se sprijina toata idempotenta.
    id_mail = (mesaj.get("Message-ID") or "").strip()
    if not id_mail:
        # Mail fara Message-ID (rar, dar exista). Ii calculam o amprenta stabila din
        # continut, ca sa nu intre de doua ori la doua rulari.
        id_mail = _id_de_rezerva(expeditor, subiect, data_primire, corp_text)

    return {
        "id": id_mail,
        "expeditor": expeditor,
        "subiect": subiect,
        "data_primire": data_primire,
        "sursa": deduce_sursa(expeditor),
        "corp_text": corp_text,
        "corp_html": corp_html,
    }


def _id_de_rezerva(expeditor: str, subiect: str, data: str, corp: str) -> str:
    """
    Fabrica un identificator stabil pentru mailurile care NU au Message-ID.

    Antetul Message-ID e obligatoriu prin standard, dar realitatea nu citeste
    standarde: exista mailuri fara el. Fara identificator, mailul nu poate intra in
    baza (e cheia primara) - iar daca am inventa unul aleator, acelasi mail ar intra
    din nou la fiecare rulare, si idempotenta s-ar rupe exact acolo unde conteaza.

    Solutia: calculam o "amprenta" (hash) din continutul mailului. Aceleasi date dau
    intotdeauna aceeasi amprenta, deci acelasi mail primeste acelasi id la fiecare
    rulare. Prefixul "amprenta:" il face vizibil in baza - vei sti ca acel id l-am
    construit noi, nu a venit din mail.
    """
    material = f"{expeditor}|{subiect}|{data}|{corp[:2000]}".encode("utf-8", "replace")
    return "amprenta:" + hashlib.sha256(material).hexdigest()[:32]


# =============================================================
# Functii care ating reteaua.
# =============================================================


def _citeste_configuratia() -> dict:
    """Citeste .env si intoarce datele de conectare, sau o eroare daca lipsesc."""
    load_dotenv(RADACINA_PROIECT / ".env")

    utilizator = os.getenv("GMAIL_USER", "").strip()
    parola = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    folder = os.getenv("GMAIL_FOLDER", "").strip()

    # Verificam intai ca avem cu ce lucra. Fara asta, eroarea de mai jos ar fi
    # "autentificare esuata", ceea ce te-ar trimite sa cauti o parola gresita
    # cand de fapt fisierul .env e gol.
    lipsesc = [
        nume
        for nume, valoare in (
            ("GMAIL_USER", utilizator),
            ("GMAIL_APP_PASSWORD", parola),
            ("GMAIL_FOLDER", folder),
        )
        if not valoare
    ]
    if lipsesc:
        return {
            "ok": False,
            "eroare": (
                f"Lipsesc din fisierul .env: {', '.join(lipsesc)}. "
                "Copiaza .env.example ca .env si completeaza valorile."
            ),
        }

    return {"ok": True, "utilizator": utilizator, "parola": parola, "folder": folder}


def _traduce_eroarea(exceptie: Exception, parola: str) -> str:
    """Traduce o eroare tehnica intr-un mesaj pe intelesul unui om."""
    if isinstance(exceptie, imaplib.IMAP4.error):
        detaliu = _ascunde_parola(str(exceptie), parola).upper()
        if "AUTHENTICATIONFAILED" in detaliu or "INVALID CREDENTIALS" in detaliu:
            return (
                "Parola de aplicatie e gresita sau revocata. "
                "Genereaza alta din setarile de securitate Google."
            )
        return f"Gmail a respins cererea: {_ascunde_parola(str(exceptie), parola)}"
    # Orice problema de retea: DNS, timp expirat, conexiune refuzata, SSL.
    return "Nu ma pot conecta la Gmail. Verifica internetul."


def _inchide_curat(conexiune) -> None:
    """
    Inchide conexiunea, orice s-ar fi intamplat inainte.

    Fara asta, o conexiune ramasa deschisa ar tine ocupata o sesiune pe serverul
    Gmail, iar Gmail limiteaza numarul de sesiuni simultane.
    """
    if conexiune is None:
        return
    try:
        conexiune.close()  # inchide folderul selectat
    except Exception:
        pass  # daca nu ajunsesem sa selectam un folder, nu e nimic de inchis
    try:
        conexiune.logout()  # inchide sesiunea, politicos
    except Exception:
        pass  # daca legatura e deja rupta, nu avem cui sa spunem "la revedere"


def _numara_conversatii(conexiune) -> int:
    """
    Cate CONVERSATII (fire de discutie) sunt in folderul deja selectat.

    DE CE existe functia asta - lectia care ne-a costat o confuzie:
    Gmail, in browser, nu iti arata mesaje. Iti arata CONVERSATII. Alertele de la
    eJobs sau BestJobs vin luna de luna cu acelasi subiect, iar Gmail le impatureste
    intr-un singur fir. Asa se face ca eticheta Joburi arata "100" pe ecran, in timp
    ce IMAP raporteaza 444 - si ambele au dreptate. Numara lucruri diferite.

    Un numar fara unitate de masura nu e o informatie. De aceea le raportam pe
    amandoua, si spunem despre fiecare ce este.

    Cum aflam: X-GM-THRID e o extensie proprie a Gmail-ului la protocolul IMAP.
    Fiecare mesaj poarta identificatorul firului din care face parte. Numaram
    identificatorii DISTINCTI - atatea conversatii sunt.

    Daca serverul nu raspunde (extensia e specifica Gmail si ar putea lipsi la alt
    furnizor), intoarcem 0. Nu e o eroare care sa merite oprirea verificarii.
    """
    try:
        # "1:*" = toate mesajele din folder, intr-o singura cerere.
        stare, linii = conexiune.fetch("1:*", "(X-GM-THRID)")
    except Exception:
        return 0

    if stare != "OK" or not linii:
        return 0

    fire = set()
    for linie in linii:
        if isinstance(linie, tuple):
            linie = linie[0]
        if not isinstance(linie, bytes):
            continue
        text = linie.decode("utf-8", errors="replace")
        # Linia arata asa:  1 (X-GM-THRID 1798234567890123456)
        marca = "X-GM-THRID"
        if marca not in text:
            continue
        dupa = text.split(marca, 1)[1]
        numar = "".join(c for c in dupa if c.isdigit())
        if numar:
            fire.add(numar)

    return len(fire)


def test_conexiune() -> dict:
    """
    Verifica daca ne putem conecta la Gmail si ce contine folderul.

    Intoarce, la reusita:
        {
            "ok": True,
            "folder": "Joburi",
            "nr_mesaje": 444,       # MESAJE - ce numara si ingestia
            "nr_conversatii": 100,  # CONVERSATII - ce iti arata Gmail in browser
            "foldere": [...],
        }
    La esec:
        {"ok": False, "eroare": "mesaj clar, pe intelesul omului"}
        - iar daca apucasem sa ne conectam, si "foldere": [...]

    Cheia se numeste `nr_mesaje`, nu `nr_mailuri`. Redenumirea e intentionata:
    "mailuri" e ambiguu (mesaje? conversatii?), iar ambiguitatea aia ne-a costat
    deja o neintelegere. Numele campului spune acum, singur, ce unitate masoara.

    Functia NU arunca exceptii in sus. Orice se strica pe drum e prins aici si
    tradus intr-un mesaj pe care il intelegi fara sa fii programator.
    """
    config = _citeste_configuratia()
    if not config["ok"]:
        return config

    conexiune = None
    try:
        conexiune = imaplib.IMAP4_SSL(
            SERVER_GMAIL, PORT_IMAP_SSL, timeout=TIMEOUT_SECUNDE
        )
        conexiune.login(config["utilizator"], config["parola"])

        # Lista TUTUROR folderelor. O cerem inainte de selectare, ca sa o avem si
        # cand selectarea esueaza - adica exact cand ai nevoie de ea, ca sa vezi
        # cum se numeste de fapt eticheta.
        stare_lista, linii = conexiune.list()
        foldere = []
        if stare_lista == "OK":
            for linie in linii:
                if isinstance(linie, bytes):
                    foldere.append(linie.decode("utf-8", errors="replace"))
                else:
                    foldere.append(str(linie))

        # readonly=True: doar ne uitam. Nu marcam nimic ca citit, nu stergem,
        # nu mutam. Cutia postala ramane exact cum era.
        nume_codificat = _codifica_nume_folder(config["folder"])
        stare, raspuns = conexiune.select(f'"{nume_codificat}"', readonly=True)

        # IMAP nu arunca eroare cand folderul nu exista: raspunde politicos "NO".
        if stare != "OK":
            return {
                "ok": False,
                "eroare": (
                    f"Folderul {config['folder']} nu exista in Gmail. Verifica eticheta "
                    "(numele e sensibil la majuscule si la spatii). "
                    "Mai jos e lista folderelor pe care le vede serverul."
                ),
                "foldere": foldere,
            }

        # raspuns[0] e raspunsul EXISTS al serverului: cate MESAJE sunt in folder.
        # E exact acelasi numar pe care il vede si ingestia prin SEARCH ALL.
        # NU e numarul de conversatii - acela se afla separat, mai jos.
        nr_mesaje = int(raspuns[0])

        return {
            "ok": True,
            "folder": config["folder"],
            "nr_mesaje": nr_mesaje,
            "nr_conversatii": _numara_conversatii(conexiune),
            "foldere": foldere,
        }

    except (imaplib.IMAP4.error, socket.gaierror, socket.timeout, TimeoutError,
            ConnectionError, ssl.SSLError, OSError) as eroare:
        return {"ok": False, "eroare": _traduce_eroarea(eroare, config["parola"])}

    finally:
        # Se executa INTOTDEAUNA - si cand totul a mers, si cand a crapat pe drum.
        _inchide_curat(conexiune)


def _deschide_folderul(config: dict):
    """
    Se conecteaza la Gmail si deschide folderul configurat, DOAR PENTRU CITIRE.

    Intoarce conexiunea deschisa, sau None daca folderul nu exista (IMAP nu arunca
    eroare in cazul asta - raspunde politicos "NO").

    readonly=True: doar ne uitam. Nu marcam nimic ca citit, nu stergem, nu mutam.
    E prima din cele doua garantii ale fisierului; a doua e BODY.PEEK, mai jos.
    """
    conexiune = imaplib.IMAP4_SSL(SERVER_GMAIL, PORT_IMAP_SSL, timeout=TIMEOUT_SECUNDE)
    conexiune.login(config["utilizator"], config["parola"])

    nume_codificat = _codifica_nume_folder(config["folder"])
    stare, _ = conexiune.select(f'"{nume_codificat}"', readonly=True)
    if stare != "OK":
        _inchide_curat(conexiune)
        return None

    return conexiune


def citeste_identificatorii(limita: int = None) -> list:
    """
    Cere Gmail-ului DOAR identificatorii mesajelor, nu si corpurile lor.

    Intoarce: [{"uid": "12", "id": "<abc@ejobs.ro>"}, ...], de la cel mai vechi la
    cel mai nou. La orice eroare intoarce o lista goala - fara exceptii in sus.

    DE CE EXISTA FUNCTIA ASTA, si e toata reparatia:
    inainte, ingestia aducea din Gmail toate mesajele CU TOT CU CORP, si abia dupa
    aceea intreba baza ce stie deja. Adica descarca ~580 de mailuri ca sa afle ca
    zero sunt noi: 103 secunde din 134, la fiecare rulare. Ordinea era inversa fata
    de cost - reteaua se platea prima, filtrul venea dupa.
    Acum se cere intai ce e ieftin (un antet are zeci de octeti; un mail, zeci de
    mii), se scade ce e deja in baza, si se descarca doar restul.

    Anteturile se cer INTR-O SINGURA cerere, nu una pe mesaj: un drum dus-intors
    pana la serverul Google costa mai mult decat datele care circula pe el.

    `limita` = cate MESAJE, cele mai recente. None = toate. Unitatea e MESAJUL, nu
    conversatia - vezi _numara_conversatii() pentru diferenta.

    UID, nu numarul de ordine al mesajului. Numerele de ordine se pot schimba intre
    doua conexiuni (daca stergi un mail de pe telefon, restul se renumeroteaza), iar
    noi facem exact asta: cerem identificatorii pe o conexiune si corpurile pe alta.
    UID-ul e stabil, deci nu putem cere din greseala alt mesaj decat cel socotit.
    """
    config = _citeste_configuratia()
    if not config["ok"]:
        return []

    conexiune = None
    try:
        conexiune = _deschide_folderul(config)
        if conexiune is None:
            return []

        # UID-urile TUTUROR mailurilor din folder. "ALL" = fara filtru.
        stare, rezultat = conexiune.uid("search", None, "ALL")
        if stare != "OK" or not rezultat or not rezultat[0]:
            return []

        uid_uri = rezultat[0].split()

        # IMAP le da in ordine cronologica: primul e cel mai vechi. Daca s-a cerut o
        # limita, luam de la coada - adica cele mai recente. "1:*" inseamna "toate",
        # si il preferam cand nu taiem nimic: e o comanda scurta, indiferent cate
        # mii de mesaje ar fi in folder.
        if limita is not None and 0 < limita < len(uid_uri):
            uid_uri = uid_uri[-limita:]
            zona = b",".join(uid_uri).decode("ascii")
        else:
            zona = "1:*"

        # BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)] = "arata-mi doar antetul Message-ID,
        # si nu atinge steagul de necitit". PEEK e a doua garantie a fisierului.
        stare, linii = conexiune.uid(
            "fetch", zona, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
        )
        if stare != "OK" or not linii:
            return []

        return _identificatorii_din_raspuns(linii)

    except (imaplib.IMAP4.error, socket.gaierror, socket.timeout, TimeoutError,
            ConnectionError, ssl.SSLError, OSError):
        # O lista goala inseamna "n-am aflat nimic", si atunci ingestia nu descarca
        # si nu salveaza nimic. Nicio pierdere: rularea urmatoare reia de la capat.
        return []

    finally:
        _inchide_curat(conexiune)


def citeste_mailurile(uid_uri: list) -> list:
    """
    Aduce din Gmail corpurile mesajelor cerute, dupa UID.

    Fiecare mail devine:
        {
            "id": "<CAF...@mail.gmail.com>",   # Message-ID
            "expeditor": "noreply@ejobs.ro",
            "subiect": "5 joburi noi pentru tine",
            "data_primire": "2026-07-13T09:15:00+03:00",
            "sursa": "ejobs",
            "corp_text": "textul mailului, fara HTML",
            "corp_html": "<html>... exact cum a venit ...",
        }

    Se cere DOAR ce i se spune. Cine alege UID-urile e core/ingestie.py, care stie
    ce e deja in baza; aici nu se decide nimic, doar se cara.

    Id-ul din dictionar se citeste DIN CORPUL ADUS, nu se ia pe incredere de la
    pasul dinainte. Asa, chiar daca intre cele doua conexiuni s-ar fi schimbat ceva
    in cutia postala, in baza intra mailul care a venit efectiv, cu id-ul lui
    adevarat - iar daca s-ar dovedi ca il aveam deja, filtrul din core il opreste.

    NU MODIFICA NIMIC IN GMAIL. Aceleasi doua garantii:
      1. folderul e deschis cu readonly=True (vezi _deschide_folderul);
      2. mailurile se cer cu BODY.PEEK[] in loc de RFC822. Diferenta e capitala:
         RFC822 aduce mailul SI il marcheaza ca citit. PEEK inseamna, literalmente,
         "trage cu ochiul" - aduce exact acelasi continut, dar nu atinge steagul de
         necitit. Fara PEEK, prima rulare ti-ar marca toate mailurile ca citite, si
         nu ai avea cum sa dai inapoi.

    La eroare intoarce ce a apucat sa citeasca. Cine apeleaza nu primeste exceptii.
    """
    if not uid_uri:
        return []

    config = _citeste_configuratia()
    if not config["ok"]:
        return []

    conexiune = None
    mailuri = []
    try:
        conexiune = _deschide_folderul(config)
        if conexiune is None:
            return []

        for uid in uid_uri:
            stare, date = conexiune.uid("fetch", str(uid), "(BODY.PEEK[])")
            if stare != "OK" or not date or not isinstance(date[0], tuple):
                # Un mail problematic (sters intre timp, de pilda) nu opreste restul.
                continue

            mailuri.append(_mail_din_octeti(date[0][1]))

        return mailuri

    except (imaplib.IMAP4.error, socket.gaierror, socket.timeout, TimeoutError,
            ConnectionError, ssl.SSLError, OSError):
        # Ce am apucat sa citim pana la eroare ramane valid si se intoarce.
        # Ce nu s-a citit, se va citi la rularea urmatoare - ingestia e idempotenta,
        # deci o rulare intrerupta nu strica nimic.
        return mailuri

    finally:
        _inchide_curat(conexiune)
