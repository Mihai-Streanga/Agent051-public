"""
Parser pentru alertele BestJobs.

Toate link-urile trec prin serverul de statistici:
    https://news.bestjobs.eu/click/4366243206/21660578/zppi/ac71a9773c/?u=<adresa reala>
Adresa reala sta in parametrul "u" si arata asa:
    joburi:  https://www.bestjobs.eu/ro/loc-de-munca/<nume-job>
    firme:   https://www.bestjobs.eu/ro/firme/<nume-firma>

Deci putem deosebi, determinist, un link de job de unul de firma: dupa calea din
adresa reala. Nu ghicim din textul afisat.

ORDINEA DIFERA INTRE EPOCI, si asta conteaza:
    2019:  [firma] [titlu job]  - firma vine INAINTE
    2024:  [titlu job] [firma]  - firma vine DUPA
    2026:  [titlu job + firma + salariu estimat + adresa + indemn], intr-un SINGUR link
De aceea nu spunem "firma e urmatorul link", ci cautam cea mai APROPIATA firma,
in ambele directii. Un parser care ar fi presupus o singura ordine ar fi mers pe
jumatate din arhiva si ar fi tacut pe cealalta jumatate.

Sablonul din 2026 nu mai are firma ca link cu text: e o poza catre /company-profile/,
fara nimic scris in ea. Deci `firma` iese goala din mail, si nu are cum sa iasa altfel -
in mail nu exista. Se completeaza din PAGINA anuntului, unde numele firmei sta scris
separat (vezi core/descriere.py). Din titlu taiem doar ce e sigur mobilier de card:
vezi FRAZE_DE_MOBILIER si curata_titlul.
"""

from agent051.parse.comun import (
    EroareParser,
    anunt,
    desfa_redirectul,
    e_text_de_navigatie,
    elemente_din_html,
    elemente_si_bucatile_linkurilor,
    fara_parametri,
    imparte_salariu_descriere,
)

SURSA = "bestjobs"

# DOUA SABLOANE, gasite in arhiva. Pana in 2019 mailurile erau in engleza si foloseau
# alte cai; din 2022, in romana. Amandoua sunt vii in arhiva, deci le recunoastem pe
# amandoua. Le tinem ca liste, nu ca sir unic: cand apare al treilea sablon, se adauga
# o linie aici, nu se rescrie parserul.
#     vechi (en):  /en/job/<nume>          /en/companies/<nume>
#     nou   (ro):  /ro/loc-de-munca/<nume> /ro/firme/<nume>
CAI_JOB = ("/loc-de-munca/", "/job/")
CAI_FIRMA = ("/firme/", "/companies/")

# ACELASI ANUNT ARE DOUA ADRESE, una per limba a site-ului:
#     https://www.bestjobs.eu/ro/loc-de-munca/<slug>
#     https://www.bestjobs.eu/en/job/<slug>
# Slug-ul e identic si e unic pe BestJobs (joburile cu acelasi nume primesc sufix:
# "hr-assistant-63", "recruiter-174-1"). Deci slug-ul, si nu adresa intreaga, e
# identitatea anuntului.
#
# DE CE conteaza: id-ul unui anunt se calculeaza din `cheie`. Cu adresa intreaga drept
# cheie, acelasi job primit intr-un mail in romana si intr-unul in engleza intra de doua
# ori in baza, ca doua oportunitati - si asa a si intrat: 91 de perechi. Se vede in
# briefing ca duplicat, iar la evaluare ar fi costat de doua ori acelasi apel de model.
#
# Forma canonica e cea FARA prefix de limba - nu "romana e adevarata si engleza e o
# copie", ci "limba paginii nu face parte din identitatea jobului". Ea e si forma pe
# care o trimit mailurile din 2026.
FORMA_CANONICA = "https://www.bestjobs.eu/loc-de-munca/"

# Mobilierul paginii, lipit de titlu in sablonul din 2026. In sablonul ala TOT cardul e
# un singur link, deci textul lui e titlul PLUS ce mai scrie in card:
#     "Multilingual HRBP (Business Partner) MIND AUTOMOBILE PART ROMANIA SRL
#      / Estimare piață pe pozitii similare: 1645 - 1820 € Strada Exemplului,
#      Brașov, România Evaluează CV cu Bestie și aplică"
# Titlul adevarat se opreste inainte de prima astfel de fraza. Le taiem aici, in mail,
# fara sa avem nevoie de pagina - iar cand pagina e luata, titlul se corecteaza exact
# (vezi core/descriere.py, extrage_firma_si_titlul).
#
# Se cauta cu litere mici, ca subsir. Fiecare fraza e scrisa in ambele limbi si in
# ambele feluri (cu si fara diacritice), fiindca sabloanele vin si asa, si asa.
FRAZE_DE_MOBILIER = (
    "/ estimare piață",
    "/ estimare piata",
    "/ market estimate",
    "evaluează cv cu bestie",
    "evalueaza cv cu bestie",
    "evaluate your cv with bestie",
)


def _e_link_de_job(url: str) -> bool:
    return any(cale in url for cale in CAI_JOB)


def _e_link_de_firma(url: str) -> bool:
    return any(cale in url for cale in CAI_FIRMA)


def identitatea(link_curat: str) -> str:
    """
    Adresa unui anunt, adusa la forma canonica: acelasi job = acelasi sir, in orice limba.

    "https://www.bestjobs.eu/en/job/hr-assistant-63"        ->
    "https://www.bestjobs.eu/ro/loc-de-munca/hr-assistant-63" ->
        amandoua: "https://www.bestjobs.eu/loc-de-munca/hr-assistant-63"

    Se foloseste ca `cheie` (din care iese id-ul), NU ca `link`. Link-ul ramane cel din
    mail, exact cum a venit: e data bruta, si e adresa care chiar a fost trimisa. Aici
    raspundem la alta intrebare - "e acelasi job?" - si atat.

    O adresa in care nu recunoastem nicio cale de job se intoarce neschimbata. Nu ghicim
    un slug dintr-o forma pe care n-am mai vazut-o; mai bine doua randuri decat doua
    joburi diferite contopite intr-unul.
    """
    for cale in CAI_JOB:
        if cale in link_curat:
            slug = link_curat.split(cale, 1)[1].split("/")[0].strip()
            if slug:
                return FORMA_CANONICA + slug
    return link_curat


def _cardul_din_link(bucati: list) -> tuple:
    """
    (titlu, firma, salariu) cand TOT cardul jobului sta in link; altfel ("", "", "").

    Sabloanele din 2026 pun intr-un singur <a>, fiecare in celula lui:
        Economist                                            <- titlul
        SILURUS                                              <- firma
        / 1140 - 1260€   sau   / Market estimate ...: ...    <- salariul (optional)
        Brașov, România                                   <- locatia
        Evaluate your CV with Bestie and apply               <- indemnul, mereu ultimul
    Lipit, textul link-ului dadea titlul "Economist SILURUS". Cardul se recunoaste dupa
    indemnul de la coada (FRAZE_DE_MOBILIER) - fara el, bucatile pot fi doar un titlu rupt
    de marcaj, si atunci nu se desparte nimic.

    Salariul se ia doar cand e oferta firmei ("/ 1140 - 1260€"). Estimarea platformei
    ("/ Market estimate on similar positions") nu e salariul oferit, deci nu se ia.
    Locatia ramane nefolosita: BestJobs o scrie ca adresa, uneori cu mai multe orase,
    iar filtrul pe oras nu se schimba fara o decizie a autorului.
    """
    if len(bucati) < 3 or not _e_mobilier(bucati[-1]):
        return "", "", ""
    salariu = ""
    for bucata in bucati[2:-1]:
        if bucata.startswith("/") and any(cifra.isdigit() for cifra in bucata):
            if not _e_mobilier(bucata):
                salariu = bucata.lstrip("/").strip()
            break
    return bucati[0], bucati[1], salariu


def _e_mobilier(text: str) -> bool:
    """Textul contine una din FRAZE_DE_MOBILIER (estimare de piata, indemnul Bestie)?"""
    marunt = (text or "").lower()
    return any(fraza in marunt or fraza.lstrip("/ ") in marunt for fraza in FRAZE_DE_MOBILIER)


def curata_titlul(text: str) -> str:
    """
    Titlul, fara mobilierul de card lipit dupa el (estimare de salariu, adresa, indemnuri).

    Taie la PRIMA fraza de mobilier gasita si arunca tot ce urmeaza - vezi
    FRAZE_DE_MOBILIER pentru sablonul care a facut-o necesara. Un titlu care nu contine
    nicio astfel de fraza (adica toate sabloanele de dinainte de 2026) se intoarce
    neatins.

    Nu incearca sa desparta numele firmei de titlu din textul lipit: acolo nu exista
    niciun semn intre ele ("... (Business Partner) MIND AUTOMOBILE PART ROMANIA SRL"), iar o
    taiere ghicita ar rupe si titluri bune. Despartirea sigura se face inainte, pe celulele
    cardului (_cardul_din_link); ce ramane lipit se completeaza din pagina anuntului.
    """
    curat = (text or "").strip()
    marunt = curat.lower()

    taieri = [marunt.find(fraza) for fraza in FRAZE_DE_MOBILIER]
    taieri = [pozitie for pozitie in taieri if pozitie > 0]
    if taieri:
        curat = curat[: min(taieri)]

    # Ce ramane se poate termina in separatorul care preceda mobilierul ("... SRL /").
    return curat.strip().rstrip("/,-").strip()

# Cat de departe cautam firma fata de titlu (in numar de elemente).
# Mic intentionat: daca firma nu e langa titlu, nu e firma jobului asta.
RAZA_CAUTARE = 4

# Fraze de subsol (indemnuri ale platformei) care apar DUPA ultimul card dintr-un mail.
# La ultimul card nu exista un link-titlu urmator care sa-l inchida, asa ca aceste
# propozitii ar aluneca in descrierea lui. Nu sunt continut de anunt - le recunoastem
# si oprim cardul acolo. Le cautam ca subsir, cu litere mici: fraza intreaga variaza
# (romana/engleza), dar miezul e stabil.
_FRAZE_FOOTER = (
    "cv-ul pentru a primi",
    "resume now",
    "mai multe detalii",
    "more details of the job",
    # Subsolul "joburi similare / asemanatoare", in engleza. Apare tot la ultimul card
    # si scapase primei liste. Fiecare fraza e distinctiva - niciuna nu apare intr-un
    # tag legitim de card (fel de munca, oras, beneficiu). "similar jobs" si "make your
    # search easier" prind cardul cu "And don't worry..."; "matching jobs" prinde
    # "Bucharest Matching jobs, still active...".
    "don't worry",
    "make your search easier",
    "similar jobs",
    "matching jobs",
)


def extrage(corp_html: str, mesaj_id: str = "?") -> list:
    """
    Sparge un mail BestJobs in anunturi individuale.

    Ridica EroareParser daca nu gaseste niciun anunt - vezi regula din comun.py.
    """
    if not corp_html or not corp_html.strip():
        raise EroareParser(SURSA, mesaj_id, "mesajul nu are corp HTML")

    elemente, bucati = elemente_si_bucatile_linkurilor(corp_html)

    # Desfacem toate link-urile o singura data, ca sa nu repetam munca la fiecare
    # cautare de firma. Lista are aceeasi lungime si aceeasi ordine ca `elemente`.
    adrese = [
        desfa_redirectul(href) if fel == "link" else ""
        for fel, href, _ in elemente
    ]

    anunturi = []
    identitati_vazute = set()

    for pozitie, (fel, _, text) in enumerate(elemente):
        if fel != "link" or not text or e_text_de_navigatie(text):
            continue
        if not _e_link_de_job(adrese[pozitie]):
            continue

        link_curat = fara_parametri(adrese[pozitie])
        cheie = identitatea(link_curat)

        # Acelasi job apare de doua-trei ori intr-un mail (titlu, "& altele", poza).
        # Il pastram o singura data - primul, care poarta titlul adevarat.
        # Comparam pe IDENTITATE, nu pe adresa: acelasi job in doua limbi are doua
        # adrese, dar e un singur job.
        if cheie in identitati_vazute:
            continue
        identitati_vazute.add(cheie)

        salariu, descriere = imparte_salariu_descriere(
            _texte_cardului(elemente, adrese, pozitie)
        )
        titlu_din_card, firma_din_card, salariu_din_card = _cardul_din_link(
            bucati.get(pozitie, [])
        )
        anunturi.append(
            anunt(
                sursa=SURSA,
                titlu=curata_titlul(titlu_din_card or text),
                firma=_firma_din_apropiere(elemente, adrese, pozitie) or firma_din_card,
                locatie="",  # BestJobs nu trimite locatia per anunt in mail
                link=link_curat,
                cheie=cheie,
                descriere=descriere,
                salariu_brut=salariu or salariu_din_card,
            )
        )

    if not anunturi:
        raise EroareParser(
            SURSA,
            mesaj_id,
            "niciun anunt gasit - sablonul s-a schimbat sau mailul nu e o alerta "
            "de joburi. Uita-te la corp_html al acestui mesaj.",
        )

    return anunturi


def joburi_din_linkuri(corp_html: str) -> set:
    """
    Identitatile tuturor joburilor spre care duce vreun link din mail - numaratoarea de control.

    Fara filtrele din extrage(): un link de job fara text (poza) sau cu text de navigare
    se numara si el. Daca extrage() scoate mai putine anunturi decat numara asta, un job
    s-a pierdut pe drum - vezi adapters/extragere.py.
    """
    identitati = set()
    for fel, href, _ in elemente_din_html(corp_html or ""):
        if fel != "link":
            continue
        adresa = desfa_redirectul(href)
        if _e_link_de_job(adresa):
            identitati.add(identitatea(fara_parametri(adresa)))
    return identitati


def _texte_cardului(elemente: list, adrese: list, pozitie: int) -> list:
    """
    Textele libere ale unui card, de sub titlu: salariu, felul muncii, oras, beneficii.

    Structura unui card BestJobs, de sus in jos:
        [link] titlu
        [link] firma
        text   / 1600 - 1900€          <- salariu
        text   Job remote              <- felul muncii
        text   Brasov               <- oras
        text   Bonus de performanta    <- beneficiu
        [link] & altele                <- se termina cardul

    Firma e un LINK asezat intre titlu si texte - il sarim, ca sa ajungem la texte.
    Orice ALT link (imaginea goala a cardului urmator, "& altele", urmatorul titlu,
    un link de footer) inseamna ca acest card s-a terminat: ne oprim. Asa nu inghitim
    textele cardului urmator si nici boilerplate-ul din subsolul mailului.
    """
    texte = []
    for indice in range(pozitie + 1, len(elemente)):
        fel, _, text = elemente[indice]
        if fel == "link":
            if not texte and _e_link_de_firma(adrese[indice]):
                continue  # firma, asezata inaintea textelor - o sarim
            break  # orice alt link inchide cardul
        if text and not e_text_de_navigatie(text):
            # Subsolul mailului, la ultimul card: nu e continut de anunt. Oprim aici.
            if any(fraza in text.lower() for fraza in _FRAZE_FOOTER):
                break
            texte.append(text)
    return texte


def _firma_din_apropiere(elemente: list, adrese: list, pozitie: int) -> str:
    """
    Cea mai apropiata firma de titlul aflat la `pozitie`.

    Cautam intai DUPA (sablonul nou), apoi INAINTE (sablonul vechi). Ne oprim la raza
    stabilita: o firma aflata la zece elemente distanta apartine altui job, nu asta.
    Daca nu gasim, intoarcem gol. Nu inventam.
    """
    for pas in range(1, RAZA_CAUTARE + 1):
        for indice in (pozitie + pas, pozitie - pas):
            if not 0 <= indice < len(elemente):
                continue
            fel, _, text = elemente[indice]
            if fel == "link" and _e_link_de_firma(adrese[indice]) and text:
                return text
    return ""
