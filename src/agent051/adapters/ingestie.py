"""
Orchestrarea ingestiei: leaga Gmail-ul, baza de date si logica din core.

Aici e locul unde codul are voie sa atinga lumea de afara. Un adaptor exista tocmai
ca sa faca legatura intre exterior (retea, disc) si logica pura din core/. Fara el,
core/ ar trebui sa stie ce e IMAP - si atunci nu ar mai fi pur.

Coregrafia, in sase pasi:
    1. intreaba baza ce id-uri are deja        -> store/db.py       (disc, ieftin)
    2. cere Gmail-ului doar identificatorii    -> ingest/gmail.py   (retea, ieftin)
    3. DECIDE ce merita descarcat              -> core/ingestie.py  (pur)
    4. aduce din Gmail doar corpurile alese    -> ingest/gmail.py   (retea, SCUMP)
    5. DECIDE ce e nou                         -> core/ingestie.py  (pur)
    6. scrie in baza ce a decis core-ul        -> store/db.py       (disc)

ORDINEA ASTA E TOATA POVESTEA. Inainte, pasul scump venea primul: se descarcau toate
mailurile cu tot cu corp, si abia apoi se intreba baza ce stie deja. Adica ~580 de
mailuri descarcate la fiecare rulare ca sa se afle ca zero sunt noi - 103 secunde din
134. Acum se plateste intai ce e ieftin (o intrebare pe disc, un antet pe retea), si
se descarca doar ce lipseste. Regula, daca vrei una singura: FILTRUL INAINTEA RETELEI.

Observa ca deciziile - singurele locuri unde se GANDESTE ceva - sunt la pasii 3 si 5,
si acolo nu exista nici retea, nici disc. Restul doar cara date. Asta e regula
proiectului, aplicata: gandirea sta separat de carat.

Zero AI aici. Ce citim, aia salvam.
"""

from agent051.core.ingestie import filtreaza_noi, uid_uri_de_adus
from agent051.ingest.gmail import citeste_identificatorii, citeste_mailurile
from agent051.store.db import (
    completeaza_html,
    id_uri_existente,
    initializeaza_db,
    salveaza_mail,
)


def ruleaza_ingestia(limita: int = None) -> dict:
    """
    Citeste mailurile din Gmail si le salveaza pe cele noi.

    Intoarce:
        {"citite": 586, "aduse": 3, "noi": 3, "sarite": 583, "html_completat": 0}

    citite = cate MESAJE are folderul (cate le-am vazut identificatorul)
    aduse  = pentru cate am descarcat efectiv corpul - adica cele pe care nu le aveam
    noi    = cate au intrat efectiv in baza
    sarite = cate erau deja acolo, sau se repetau in aceeasi citire

    A doua rulare, la rand, pe aceleasi mailuri, trebuie sa dea:
        {"citite": 586, "aduse": 0, "noi": 0, "sarite": 586}
    E cel mai simplu test pe care il poti face singur: ruleaza de doua ori si uita-te
    la cifre. Daca a doua oara "noi" nu e 0, datele se dubleaza. Daca "aduse" nu e 0,
    se descarca degeaba - adica exact defectul reparat aici.
    """
    # Pasul 0: ne asiguram ca tabela exista. Daca exista deja, nu face nimic.
    initializeaza_db()

    # Pasul 1: discul. Intrebam PRIMA baza ce stie deja - e cea mai ieftina intrebare
    # din tot fluxul, si e cea care face restul sa nu mai coste.
    deja_in_baza = id_uri_existente()

    # Pasul 2: reteaua, partea ieftina. Doar identificatorii, fara corpuri.
    identificatori = citeste_identificatorii(limita=limita)

    # Pasul 3: gandirea. Functie pura - primeste doua liste de date si intoarce una
    # noua. Nu stie de unde vin datele si nici unde se duc.
    de_adus = uid_uri_de_adus(identificatori, deja_in_baza)

    # Pasul 4: reteaua, partea scumpa. Se descarca DOAR ce s-a hotarat la pasul 3.
    mailuri = citeste_mailurile(de_adus)

    # Pasul 5: gandirea, a doua oara. Nu e de prisos: pasul 3 a lucrat pe anteturi,
    # deci n-a putut recunoaste mesajele fara Message-ID (alea se aduc mereu, si abia
    # din corp li se poate calcula amprenta). Aici se decide pe id-ul adevarat.
    de_salvat = filtreaza_noi(mailuri, deja_in_baza)

    # Pasul 6: discul. Scriem ce a decis core-ul.
    #
    # De ce mai folosim INSERT OR IGNORE in db.py, daca am filtrat deja de doua ori:
    # filtrarea e o optimizare (nu mai incercam scrieri inutile), dar GARANTIA ca nu
    # apar duplicate ramane a bazei de date, prin cheia primara. Doua rulari pornite
    # simultan ar putea sa filtreze pe aceeasi lista, si atunci singurul aparator e
    # baza. Nu ne bazam pe noroc acolo unde putem avea o certitudine.
    noi = 0
    for mail in de_salvat:
        a_intrat = salveaza_mail(
            id_mail=mail["id"],
            expeditor=mail["expeditor"],
            subiect=mail["subiect"],
            data_primire=mail["data_primire"],
            sursa=mail["sursa"],
            corp_text=mail["corp_text"],
            corp_html=mail.get("corp_html", ""),
        )
        if a_intrat:
            noi += 1

    # Pasul 7: reparam trecutul.
    #
    # Cele 444 de mesaje au intrat in baza inainte sa pastram HTML-ul, iar fara el nu
    # avem link-urile anunturilor. Pasul asta le completeaza. Scrie DOAR unde corp_html
    # e gol - un HTML deja salvat nu se rescrie niciodata.
    #
    # ATENTIE, i s-a INGUSTAT bataia o data cu reparatia de mai sus: acum se uita doar
    # la mailurile ADUSE in rularea asta, fiindca doar alea sunt in memorie. In practica
    # nu pierdem nimic - la 16 august 2026, in baza nu mai exista niciun mesaj fara HTML,
    # deci treaba era terminata. Daca vreodata va fi nevoie de un backfill nou, el nu se
    # mai poate face pe furis, aici: se cer bazei mesajele carora le lipseste coloana si
    # se aduc din Gmail exact alea, dupa UID.
    html_completat = 0
    for mail in mailuri:
        if completeaza_html(mail["id"], mail.get("corp_html", "")):
            html_completat += 1

    return {
        "citite": len(identificatori),
        "aduse": len(mailuri),
        "noi": noi,
        "sarite": len(identificatori) - noi,
        "html_completat": html_completat,
    }
