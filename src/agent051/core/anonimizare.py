"""
Curatarea datelor personale din textul care pleaca din agent catre altcineva.

DE CE EXISTA. Raportul extragerii intoarce, pentru fiecare mesaj pe care parserul nu l-a
putut sparge, SUBIECTUL mailului. Subiectul e ce ne trebuie ca sa recunoastem un sablon
nou de platforma - "Bun venit pe eJobs" nu e o problema, "joburi noi pentru tine" e. Dar
subiectele mailurilor nu sunt scrise de platforma pentru noi, ci pentru CINEVA: contin
nume de persoane, iar unul din arhiva contine un cod PIN. Raportul ajunge la JA.S.Mine, care
il poate afisa pe ecran - deci datele alea ar ajunge la vedere fara ca cineva sa fi cerut
asta.

Deci nu scoatem subiectul din raport (si-ar pierde rostul), ci il curatam.

PRINCIPIUL, si e singurul care conteaza cand nu poti fi sigur:
    CE NU SE POATE DECIDE SIGUR, SE TAIE.
Un subiect scurtat isi pastreaza utilitatea de diagnostic - cuvintele care tradeaza un
sablon nou ("alerta", "joburi", "candidatura") sunt tocmai cele obisnuite, scrise cu
litera mica. Un nume scapat, in schimb, nu se mai recupereaza: odata afisat, a fost
afisat. Cele doua greseli posibile nu costa la fel, deci nu le tratam la fel.

CE NU FACE FISIERUL ASTA, si e important:
nu curata baza de date. In `mailuri` subiectul ramane BRUT, exact cum a venit - e data
bruta, iar regula proiectului spune limpede ca ingestia nu curata. Ce
arunci la ingestie nu mai poti recupera; ce cureti la iesire se poate oricand recalcula
altfel. Functia asta se aplica DOAR pe drumul catre afara.

FUNCTIE PURA, ca tot ce e in core/: primeste un sir, intoarce un sir. Singurul import
e `re`, din Python.
"""

import re

# Cat de lung poate fi un subiect curatat. Peste atat, se taie.
#
# Nu e o regula de estetica: cu cat un text e mai lung, cu atat are mai multe sanse sa
# contina ceva ce regulile de mai jos n-au recunoscut. Un sablon de platforma se
# recunoaste din primele cuvinte; restul e, aproape mereu, continut adresat unei persoane.
LUNGIME_MAXIMA = 100

# Semnele puse in loc. Se vad in raport, deci spun EXACT ce s-a taiat - un raport din care
# nu se intelege ca s-a taiat ceva e un raport in care ai incredere pe nedrept.
SEMN_EMAIL = "[email]"
SEMN_NUMAR = "[numar]"
SEMN_TAIAT = "[...]"

# O adresa de e-mail: ceva, un @, ceva cu punct. Nu incercam sa fim exacti dupa standard -
# aici nu validam adrese, ci le RECUNOASTEM ca sa le stergem. Un tipar larg taie mai mult
# decat trebuie, ceea ce e exact directia in care vrem sa greseasca.
TIPAR_EMAIL = re.compile(r"\S+@\S+\.\S+")

# Un sir de cel putin patru cifre, chiar despartite de spatii, puncte, liniute sau
# paranteze: numere de telefon ("07xx xxx xxx"), coduri PIN, numere de comanda, ani.
#
# DE CE PATRU si nu mai multe: un PIN are patru. Pierdem cifre nevinovate - un "2026"
# dintr-un subiect devine [numar] - si e in regula: anul nu ajuta la recunoasterea unui
# sablon, iar un PIN afisat pe ecran nu se mai poate lua inapoi. Cifrele mici raman
# intregi, deci "34 joburi pentru tine" ramane citibil, cu tot cu cifra care conteaza.
TIPAR_NUMAR = re.compile(r"\d[\d\s.\-()]{2,}\d")

# Un cuvant care incepe cu majuscula, inclusiv cu diacritice romanesti.
# \w acopera si literele cu semne, dar avem nevoie sa stim daca PRIMA litera e mare -
# de aia comparam cuvantul cu varianta lui cu initiala mare.
TIPAR_CUVANT = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)


def curata_subiectul(subiect: str) -> str:
    """
    Subiectul unui mail, fara ce e sau ar putea fi data personala. Pentru RAPOARTE, nu
    pentru baza.

    Se aplica, in ordine:
      1. adresele de e-mail        -> [email]
      2. sirurile de >= 4 cifre    -> [numar]   (telefoane, PIN-uri, ani, numere de comanda)
      3. TOATE cuvintele cu MAJUSCULA -> [...]
      4. ce trece de 100 de caractere se taie

    REGULA 3 E CEA CARE FACE TREABA, si merita explicata, fiindca pare brutala.
    Nu exista niciun fel de a recunoaste un nume de persoana cu o regula: "Ion", "Mihai"
    si "Popescu" arata exact ca "Brasov", "eJobs" si "Bucuresti". Pe cele 47 de esecuri
    din arhiva, nici macar unul nu continea o adresa de e-mail, si doar doua contineau
    cifre - dar sapte se terminau cu doua cuvinte cu majuscula lipite, adica exact forma
    "Prenume Nume". Un filtru care ar cauta doar e-mailuri si telefoane ar fi ratat fix
    ce trebuia sa prinda.

    NICIO EXCEPTIE PENTRU PRIMUL CUVANT, si asta a fost invatat pe date reale.
    Prima versiune pastra primul cuvant al subiectului, cu argumentul ca propozitiile
    incep cu majuscula din gramatica, nu fiindca ar fi nume. Rulata pe arhiva, a lasat la
    vedere zece subiecte care incepeau exact cu prenumele destinatarului - fiindca asa isi
    scrie LinkedIn subiectele. Adica exceptia scapa taman cazul cel mai frecvent. Pretul
    renuntarii la ea e mic: "Alerta zilnica de joburi" devine "[...] zilnica de joburi",
    care se recunoaste la fel de bine.

    Se pierd pe drum si nume de firme si de orase. Nu incercam sa le salvam: nu se pot
    deosebi de nume de oameni, iar sursa mesajului se vede oricum separat in raport.

    Un subiect gol iese gol. Nu inventam un text care nu exista.
    """
    if not subiect or not subiect.strip():
        return ""

    curat = TIPAR_EMAIL.sub(SEMN_EMAIL, subiect)
    curat = TIPAR_NUMAR.sub(SEMN_NUMAR, curat)
    curat = _taie_cuvintele_cu_majuscula(curat)

    curat = " ".join(curat.split())

    if len(curat) > LUNGIME_MAXIMA:
        curat = curat[:LUNGIME_MAXIMA].rstrip() + "…"

    return curat


def _taie_cuvintele_cu_majuscula(text: str) -> str:
    """
    Inlocuieste cu [...] fiecare cuvant care incepe cu majuscula. Fara exceptii.

    Fara exceptii nici macar pentru primul cuvant: pe arhiva reala, zece subiecte incepeau
    chiar cu prenumele destinatarului. Vezi nota din curata_subiectul().

    Doua cuvinte taiate unul dupa altul dau un singur semn, nu doua: "[...] [...]" nu
    spune mai mult decat "[...]" si face raportul greu de citit. Iar cate cuvinte avea
    numele cuiva e tot o informatie despre acel cineva.
    """
    bucati = []
    ultima_pozitie = 0

    for gasit in TIPAR_CUVANT.finditer(text):
        cuvant = gasit.group(0)
        incepe_cu_majuscula = cuvant[0] != cuvant[0].lower()

        if incepe_cu_majuscula:
            bucati.append(text[ultima_pozitie : gasit.start()])
            bucati.append(SEMN_TAIAT)
            ultima_pozitie = gasit.end()

    bucati.append(text[ultima_pozitie:])
    rezultat = "".join(bucati)

    # Semnele lipite (dupa doua nume unul langa altul) se string intr-unul singur.
    return re.sub(r"(\[\.\.\.\][\s,;:.\-]*)+", SEMN_TAIAT + " ", rezultat).strip()
