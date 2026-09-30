"""
Ce fel de mesaj e unul din care nu s-a putut extrage niciun anunt.

DE CE EXISTA FISIERUL ASTA. Raportul extragerii spunea, pana acum, un singur numar:
"52 de mesaje esuate". Numarul ala amesteca doua lucruri care nu au nimic in comun:

  1. mailuri care n-au fost NICIODATA alerte de joburi - bun venit, coduri PIN,
     "ai aplicat cu succes", notificari de puzzle-uri. Din ele nu e nimic de extras,
     si asta nu se va schimba niciodata;
  2. mailuri care ERAU alerte, dar din care parserul n-a stiut sa scoata joburile -
     fiindca platforma si-a schimbat sablonul.

Al doilea caz inseamna joburi pierdute. Primul nu inseamna nimic. Iar cat timp
amandoua se aduna in acelasi total, al doilea e INVIZIBIL: 52 devine 53, si cine se
uita vede o cifra care oricum era mare.

Asta e datoria pe care o inchide fisierul: separa cele doua cauze, ca sa existe o
cifra care sa aiba voie sa fie 0 - `de_verificat`. Cand ea nu mai e 0, te uiti.

DIRECTIA IN CARE GRESIM, si e aleasa deliberat:
recunoastem doar ce am vazut cu ochii nostri, in arhiva reala. TOT restul cade in
`de_verificat`. Deci un mail de reclama nou, nevinovat, va aparea acolo si te va pune
sa te uiti degeaba - o alarma falsa. Regula inversa (sa cautam cuvinte de tip "joburi
noi" si sa consideram restul nevinovat) ar fi mai linistita si mai gresita: un sablon
nou, cu alte cuvinte in subiect, ar trece drept "nu e alerta" si nu s-ar vedea deloc.
O alarma falsa se inchide dintr-o privire; un job pierdut in tacere, nu.

FUNCTIE PURA, ca tot ce e in core/: primeste un sir, intoarce un sir. Nu atinge nici
reteaua, nici discul, nici baza.

ATENTIE: se aplica pe subiectul BRUT, nu pe cel curatat de core/anonimizare.py.
Curatarea taie cuvintele cu majuscula, deci din "Bun venit pe eJobs" ar ramane
"[...] venit pe eJobs" - adica exact cuvintele dupa care recunoastem sablonul.
Subiectul brut intra aici si se opreste aici: din functie iese doar o eticheta din
cele trei de mai jos. Raportul afiseaza tot varianta curatata.
"""

import re

from agent051.core.text import fara_diacritice

# Cele trei etichete. Codul de afara le compara ca text, deci stau ca nume, o data.
NU_E_ALERTA = "nu_e_alerta"
ALERTA_FARA_LINKURI = "alerta_fara_linkuri"
DE_VERIFICAT = "de_verificat"

# Tiparele de mai jos se scriu FARA diacritice, cu literele de pe orice tastatura:
# subiectul trece intai prin fara_diacritice (core/text.py), deci un tipar scris cu
# "ș" n-ar mai prinde nimic - si n-ar spune de ce.

# Mailuri care SUNT despre joburi, dar al caror sablon nu contine link-uri catre
# anunturi individuale. Nu e nimic de reparat in parser: in mailurile astea chiar nu
# exista joburi de luat, doar link-uri catre cautari. Le numaram separat fiindca ele
# inseamna, totusi, oportunitati pe care nu le vedem - spre deosebire de un bun venit.
TIPARE_ALERTA_FARA_LINKURI = [
    r"companiile au facut angajari",      # rezumatul vechi LinkedIn: "...181 de posturi"
    r"fac angajari",                      # "X si Y fac angajari"
    r"a distribuit un anunt nou",         # o firma distribuie un anunt pe pagina ei
    r"va cautati un job nou",             # LinkedIn: preferinte de job, link-uri spre cautari
]

# Mailuri care n-au fost niciodata alerte de joburi. Fiecare tipar e scris dupa un
# mesaj vazut in arhiva - nu ghicim sabloane pe care nu le-am intalnit.
TIPARE_NU_E_ALERTA = [
    # cont si securitate
    r"bun venit",
    r"confirma inregistrarea",
    r"codul dvs\.? pin|cod pin",
    r"schimbare a parolei|parola dvs\.? a fost resetata",
    r"link logare",
    r"inregistrare pe dispozitiv nou",
    # activitate pe platforma, fara legatura cu anunturile
    r"ai aplicat cu succes|you have successfully applied",
    r"alerta vizualizare cv",
    r"new message on|mesaj nou pe",
    r"nu ratati conversatiile din grupul",
    # retea de contacte (LinkedIn)
    r"adaugati-ma in reteaua",
    r"incepeti o conversatie",
    r"vedeti pe cine cunoasteti",
    r"vizualizati contactele",
    r"invited you to follow",
    r"sunteti disponibil pentru lucru|sunt disponibili pentru lucru",
    r"informati recrutorii",
    # jocul zilnic LinkedIn
    r"puzzle|aptitudine noua disponibila|este randul dvs",
    # reclame. Nu exista regula generala pentru reclame, deci sunt prinse pe textul
    # lor propriu. Tiparele astea doua sunt inguste tocmai fiindca asa trebuie:
    # o reclama noua NU se va potrivi, si atunci va iesi la "de_verificat".
    r"am lansat easyjobs",
    r"talent hunter",
]


def felul_esecului(subiect: str) -> str:
    """
    Din subiectul BRUT al unui mail din care nu s-a extras nimic, ce fel de mail e.

    Intoarce una din trei:
        "alerta_fara_linkuri" - e despre joburi, dar sablonul n-are link-uri per job
        "nu_e_alerta"         - n-a fost niciodata o alerta (bun venit, PIN, puzzle...)
        "de_verificat"        - nerecunoscut. UITA-TE LA EL.

    Ordinea conteaza: intrebam intai daca e o alerta fara link-uri. Un mesaj de tip
    "companiile au facut angajari" e despre joburi chiar daca ar contine si un cuvant
    din lista cealalta - iar eticheta care costa ceva e cea care trebuie sa castige.

    Un subiect gol iese "de_verificat". Nu presupunem nimic despre un mail despre care
    nu stim nimic - si un subiect gol e exact asta.
    """
    # Un subiect lipsa din baza e tot "nu stim nimic", ca unul gol.
    curat = fara_diacritice(subiect or "")
    if not curat.strip():
        return DE_VERIFICAT

    for tipar in TIPARE_ALERTA_FARA_LINKURI:
        if re.search(tipar, curat):
            return ALERTA_FARA_LINKURI

    for tipar in TIPARE_NU_E_ALERTA:
        if re.search(tipar, curat):
            return NU_E_ALERTA

    return DE_VERIFICAT
