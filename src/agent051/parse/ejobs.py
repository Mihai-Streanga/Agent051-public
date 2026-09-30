"""
Parser pentru alertele eJobs.

DOUA SABLOANE, dupa epoca. Amandoua trebuie sa mearga - arhiva are 11 ani.

  Pana in 2019 - link direct catre anunt:
      https://www.ejobs.ro/user/locuri-de-munca/1103450/?utm_source=...

  Din 2022 - link de urmarire, cu adresa reala ascunsa in base64:
      http://cb.mta.ejobs.ro/erdr/<...>-1-0-aHR0cHM6...
      care se desface in:
      https://www.ejobs.ro/user/locuri-de-munca/j/1756111?utm_source=...

  Nu tratam cele doua cazuri separat. Desfacem intai orice link de urmarire (vezi
  comun.desfa_redirectul), si abia apoi ne uitam la adresa reala. Asa, ambele epoci
  ajung la aceeasi verificare: "e o adresa de anunt eJobs, cu numar?".

Structura unui anunt in mail: titlul e textul din link, iar firma e textul liber
care urmeaza imediat dupa. Locatia NU e trimisa per anunt in mailurile eJobs -
o lasam goala. Nu o inventam si nu o ghicim din altceva.
"""

import re

from agent051.parse.comun import (
    EroareParser,
    anunt,
    curata_textul,
    desfa_redirectul,
    e_text_de_navigatie,
    elemente_din_html,
    fara_parametri,
)

SURSA = "ejobs"

# TREI sabloane de adresa, toate vii in arhiva:
#     /user/locuri-de-munca/1103450/                 (2018 - numar)
#     /user/locuri-de-munca/consilier-vanzare.../    (2019 - nume, nu numar)
#     /user/locuri-de-munca/j/1756111                (2022+ - numar, dupa un "j/")
#
# Ce le uneste: bucata "/user/locuri-de-munca/", urmata de ceva.
# Ce NU e un anunt: "/locuri-de-munca/brasov" - o pagina de CAUTARE pe oras.
# Observa ca acesteia ii lipseste "/user/" - de asta cerem "/user/" in tipar.
# Fara acea distinctie, fiecare mail ar fi produs un "anunt" fals catre lista Brasov.
TIPAR_ANUNT = re.compile(r"/user/locuri-de-munca/(?:j/)?([^/?#]+)")

# Numarul anuntului, la capatul adresei, oricare ar fi bucata dinaintea lui:
#     /user/locuri-de-munca/1103450
#     /user/locuri-de-munca/j/1984459
#     /user/locuri-de-munca/implementator-software-salarizare-si-resurse-umane/1984459
# Ultimele doua sunt ACELASI anunt, venit in doua tipuri de mail (63 de perechi in baza,
# 30 septembrie 2026). Forma din 2019, doar cu nume si fara numar, nu se potriveste aici.
TIPAR_NUMAR = re.compile(r"/user/locuri-de-munca/(?:[^/?#]+/)?(\d+)$")

# Forma la care se aduce orice adresa cu numar: cea din mailurile de dupa 2022, adica
# forma care vine si de acum inainte. Id-ul e intern, deci alegerea nu se vede in afara.
FORMA_CANONICA = "https://www.ejobs.ro/user/locuri-de-munca/j/"


# Insigne de interfata asezate INTRE titlu si firma. Nu sunt continut de anunt.
#
# Sablonul cu insigna arata asa:
#     [link] Dispecer Transport      <- titlul
#            Nou                     <- insigna (badge), nu firma
#            | INTERNATIONAL ALEXANDER  <- firma, cu separatorul lipit de ea
# Parserul vechi lua primul text de dupa titlu si il trecea drept firma - asa au ajuns
# 265 de anunturi cu firma "Nou". Aceeasi specie ca bug-ul "Recrutează activ" de la
# LinkedIn: o eticheta de interfata luata drept data despre job.
#
# Se compara cu litere mici. O firma nu se numeste "Nou" - iar daca vreodata s-ar numi,
# o firma pierduta e mai ieftina decat 265 de firme false.
INSIGNE = {"nou", "new"}

# Semnele cu care sablonul desparte insigna de firma. Se taie din capul textului, ca
# firma sa nu intre in baza drept "| INTERNATIONAL ALEXANDER".
SEPARATOARE = "|·-–— \t"

# Cate texte libere de dupa titlu se aduna intr-un nume de firma.
#
# Nu e o cifra aleasa cu degetul: eJobs pune punctele din numele firmei in etichete
# separate ("S<span>.</span>C<span>.</span> HATTRICK BET S<span>.</span>R<span>.</span>L"),
# deci un singur nume ajunge la noi rupt in zece bucati. Trebuie lipite la loc.
# Verificat pe toate cele 206 mailuri eJobs din arhiva: cu plafonul asta, cel mai lung
# nume iesit are 60 de caractere - deci nu inghite niciodata textul de dupa card.
LIMITA_BUCATI_FIRMA = 25

# Texte care NU fac parte din numele firmei si care OPRESC adunarea bucatilor.
#
# Fara ele, ultimul card al unui mail inghite ce urmeaza dupa el si ies firme numite
# "Axen Group As S.R.L.Compania" sau "SKILLD by eJobsDacă nu vrei să mai primești
# alerte:". Aceeasi problema si aceeasi solutie ca la _FRAZE_FOOTER din bestjobs.py:
# la ultimul card nu exista un link urmator care sa-l inchida.
#
# Lista NU e ghicita - iese din numaratoarea a tot ce apare dupa un nume de firma in
# cele 206 mailuri eJobs din arhiva. Doua lucruri, si numai doua: eticheta "Compania" si
# randul de dezabonare. Restul erau, fara exceptie, continuari legitime de nume.
#
# "Compania" se cauta ca text INTREG, nu ca bucata: o firma chiar se poate numi
# "Compania de Apa Brasov", si aia n-are voie sa fie taiata.
OPRESTE_FIRMA_INTREG = {"compania"}
OPRESTE_FIRMA_SUBSIR = (
    "nu vrei sa mai primesti alerte",
    "nu vrei să mai primești alerte",
)


def _e_anunt(url: str) -> bool:
    """Adresa asta duce la un anunt anume (nu la o cautare, nu la un meniu)?"""
    return bool(TIPAR_ANUNT.search(url))


def identitatea(link_curat: str) -> str:
    """
    Adresa unui anunt, adusa la forma canonica: acelasi numar de anunt = acelasi sir.

    ".../locuri-de-munca/j/1984459"                        ->
    ".../locuri-de-munca/implementator-software-.../1984459" ->
        amandoua: "https://www.ejobs.ro/user/locuri-de-munca/j/1984459"

    Ca la BestJobs (parse/bestjobs.py): se foloseste ca `cheie`, din care iese id-ul, nu
    ca `link`. Link-ul ramane cel din mail - e data bruta.

    O adresa fara numar (forma din 2019) se intoarce neschimbata. Nu ghicim un numar din
    nume; mai bine doua randuri decat doua joburi diferite contopite intr-unul.
    """
    potrivire = TIPAR_NUMAR.search(link_curat or "")
    if potrivire:
        return FORMA_CANONICA + potrivire.group(1)
    return link_curat


def extrage(corp_html: str, mesaj_id: str = "?") -> list:
    """
    Sparge un mail eJobs in anunturi individuale.

    Ridica EroareParser daca nu gaseste NICIUN anunt. Asta e intentionat: un mail de
    alerta eJobs FARA joburi nu exista. Daca nu am gasit niciunul, inseamna ca sablonul
    s-a schimbat si parserul e depasit - si vrem sa aflam acum, cu un mesaj clar, nu
    peste trei luni, dintr-o baza de date goala.
    """
    if not corp_html or not corp_html.strip():
        raise EroareParser(SURSA, mesaj_id, "mesajul nu are corp HTML")

    # pastreaza_marginile=True: numele firmelor vin rupte in bucati de marcajul mailului
    # si trebuie lipite la loc fara sa se piarda spatiile dintre ele. Vezi _firma_de_dupa.
    elemente = elemente_din_html(corp_html, pastreaza_marginile=True)
    anunturi = []
    linkuri_vazute = set()

    for pozitie, (fel, href, text) in enumerate(elemente):
        if fel != "link" or not text or e_text_de_navigatie(text):
            continue

        adresa_reala = desfa_redirectul(href)
        if not _e_anunt(adresa_reala):
            continue  # link de meniu, de cautare, de dezabonare, de aplicatie mobila

        link_curat = fara_parametri(adresa_reala)
        cheie = identitatea(link_curat)

        # Acelasi job apare de doua ori in mail: o data pe titlu, o data pe poza
        # (link fara text). Il pastram o singura data - primul, cel cu titlul.
        # Se compara cheia, nu link-ul: cele doua pot veni in forme diferite.
        if cheie in linkuri_vazute:
            continue
        linkuri_vazute.add(cheie)

        # descriere si salariu_brut raman GOALE la eJobs, si e o decizie, nu o scapare.
        # Am verificat pe toata arhiva (206 mailuri): cardul eJobs e doar titlu + firma.
        # Nu exista niciun salariu afisat per anunt, si nicio descriere. Ce se putea
        # "recupera" de sub titlu era doar zgomot - eticheta "Compania", subsolul de
        # dezabonare al ultimului anunt, uneori numele firmei ratacit acolo cand badge-ul
        # "Nou" e luat drept firma. Un camp umplut cu zgomot e mai rau decat unul gol:
        # pe cel gol il vezi. Deci nu extragem nimic aici - vezi anunt(), care le lasa "".
        anunturi.append(
            anunt(
                sursa=SURSA,
                titlu=text,
                firma=_firma_de_dupa(elemente, pozitie),
                locatie="",  # eJobs nu trimite locatia per anunt in mail
                link=link_curat,
                cheie=cheie,
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
    Link-urile curate ale tuturor anunturilor din mail - numaratoarea de control.

    Fara filtrele din extrage(): si link-ul de pe poza (fara text) se numara. Daca
    extrage() scoate mai putine anunturi decat numara asta, un job s-a pierdut pe drum -
    vezi adapters/extragere.py.
    """
    linkuri = set()
    for fel, href, _ in elemente_din_html(corp_html or ""):
        if fel != "link":
            continue
        adresa = desfa_redirectul(href)
        if _e_anunt(adresa):
            # Identitatea, nu adresa: doua forme ale aceluiasi anunt sunt un singur job.
            linkuri.add(identitatea(fara_parametri(adresa)))
    return linkuri


def _firma_de_dupa(elemente: list, pozitie: int) -> str:
    """
    Firma e primul text liber care urmeaza dupa titlu.

    In mail arata asa, de sus in jos:
        [link] Specialist Marketing      <- titlul
               SABRINI                   <- firma (text simplu, fara link)
        [link] Business Developer        <- urmatorul job
               Bookster

    Ne oprim cand dam de urmatorul link: acolo incepe deja alt job, deci firma
    jobului curent nu mai poate veni. Daca nu gasim nimic, intoarcem gol - si asta
    se vede in raport. Nu inventam o firma.

    "Primul text" nu inseamna insa "orice text", si nici macar "un singur text":

      - intre titlu si firma se poate strecura o INSIGNA ("Nou"). Pe aia o sarim. Firma
        vine atunci cu separatorul lipit de ea ("| INTERNATIONAL ALEXANDER"), deci il
        taiem din capete.
      - numele firmei poate fi RUPT in mai multe texte de catre marcajul mailului:
        "S<span>.</span>C<span>.</span> HATTRICK BET S<span>.</span>R<span>.</span>L".
        Din el, un parser care ia primul text intoarce "S" - si exact asa au ajuns in
        baza opt firme numite "S". Deci adunam toate textele pana la urmatorul link si
        le lipim la loc, cu spatiile de la margini cu tot (vezi elemente_din_html,
        pastreaza_marginile).

    Adunam pana la urmatorul link fiindca la eJobs un card are DOAR titlu si firma - nu
    mai urmeaza nimic altceva de textul liber pana la jobul urmator.
    """
    bucati = []
    for fel, _, text in elemente[pozitie + 1 : pozitie + 1 + LIMITA_BUCATI_FIRMA]:
        if fel == "link":
            break  # a inceput alt job
        if not text or e_text_de_navigatie(text):
            continue
        if text.strip().lower() in INSIGNE:
            continue  # insigna de interfata, nu firma - firma vine dupa ea

        marunt = text.strip().lower()
        if marunt in OPRESTE_FIRMA_INTREG or any(f in marunt for f in OPRESTE_FIRMA_SUBSIR):
            break  # aici s-a terminat numele si a inceput mailul

        bucati.append(text)

    return curata_textul("".join(bucati)).strip(SEPARATOARE).strip()
