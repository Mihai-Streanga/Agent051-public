"""
Logica ingestiei: ce e nou si ce am vazut deja.

Doua decizii, si amandoua raspund aceleiasi intrebari, in doua momente diferite:
  - uid_uri_de_adus()  - INAINTE de descarcare: ce merita adus din Gmail?
  - filtreaza_noi()    - DUPA descarcare: ce merita scris in baza?
A doua nu e de prisos. Prima lucreaza pe anteturi, deci nu poate sti nimic despre
mesajele care n-au Message-ID; a doua lucreaza pe mailul intreg, cu id-ul lui
adevarat. Prima e o economie, a doua e garantia.

Fisierul asta contine DOAR functii pure: primesc date, intorc date. Nu ating
reteaua, nu ating discul, nu stiu ca exista Gmail sau SQLite. Poti citi codul de
mai jos fara sa stii nimic despre IMAP sau baze de date - si asta e tot rostul.

De ce conteaza: o functie pura se poate verifica pe loc, cu date inventate, fara
internet si fara cont de mail. Vezi tests/test_ingestie.py - testul de acolo ruleaza
in cateva milisecunde, oriunde, si nu poate strica nimic. Daca aceeasi logica ar sta
amestecata cu conexiunea la Gmail, ar trebui sa te conectezi la Gmail ca sa o testezi.

Orchestrarea (cine cheama Gmail-ul, cine scrie in baza) sta in adapters/ingestie.py.
"""


def uid_uri_de_adus(identificatori: list, id_uri_existente: set) -> list:
    """
    Din identificatorii vazuti in Gmail, pentru care mesaje merita descarcat corpul.

    identificatori   - [{"uid": "12", "id": "<abc@ejobs.ro>"}, ...], asa cum ii da
                       ingest/gmail.py dupa ce a cerut DOAR anteturile
    id_uri_existente - Message-ID-urile aflate deja in baza de date

    Intoarce lista UID-urilor de adus, in ordinea primita.

    DE CE EXISTA, si e reparatia unei rulari de 134 de secunde:
    un antet costa zeci de octeti, un mail intreg costa zeci de mii. Daca intrebam
    intai ce avem si descarcam numai restul, o rulare pe care nu s-a schimbat nimic
    nu mai are ce sa descarce. Decizia asta - singurul loc unde se gandeste ceva -
    e aici, deci se poate verifica fara internet si fara cutie postala.

    UN MESAJ FARA MESSAGE-ID SE ADUCE INTOTDEAUNA.
    Fara antet nu avem cu ce sa-l recunoastem, iar id-ul lui se poate calcula abia
    din corp (o amprenta a continutului - vezi _id_de_rezerva din ingest/gmail.py).
    Deci il descarcam si lasam filtrul de dupa sa decida daca il aveam deja. Alegerea
    costa cateva descarcari inutile pe rulare; alegerea cealalta - sa-l sarim - ar
    pierde un mail pe tacute, iar un mail pierdut nu se vede nicaieri.

    Un mesaj care apare de doua ori (acelasi Message-ID sub doua etichete Gmail) se
    aduce o singura data. Primul castiga, ca la filtreaza_noi().
    """
    de_adus = []
    vazute_acum = set()

    for identificator in identificatori:
        uid = identificator.get("uid")
        if not uid:
            continue  # fara UID nu avem ce cere serverului

        id_mail = identificator.get("id")

        if not id_mail:
            de_adus.append(uid)  # nerecunoscut fara corp - vezi explicatia de sus
            continue

        if id_mail in id_uri_existente:
            continue  # il avem din alta rulare

        if id_mail in vazute_acum:
            continue  # a aparut de doua ori chiar in citirea asta

        vazute_acum.add(id_mail)
        de_adus.append(uid)

    return de_adus


def filtreaza_noi(mailuri: list, id_uri_existente: set) -> list:
    """
    Din mailurile citite, le pastreaza doar pe cele pe care nu le avem deja.

    mailuri          - lista de dictionare, asa cum vin din Gmail
    id_uri_existente - Message-ID-urile aflate deja in baza de date

    Intoarce o lista noua, cu mailurile de salvat. Lista primita nu e modificata:
    functia nu strica ce i se da, ci construieste altceva. Asta face codul previzibil -
    cine o apeleaza stie ca datele lui raman intacte.

    Doua feluri de duplicate, si le prindem pe amandoua:

      1. Mail deja in baza (l-am ingerat la o rulare anterioara).
         Il sarim - de asta primim id_uri_existente.

      2. Acelasi mail de doua ori in ACEEASI citire.
         Se intampla: un mail poate aparea sub doua etichete Gmail, si atunci IMAP
         il raporteaza de doua ori. Fara verificarea asta, am incerca sa-l scriem de
         doua ori in aceeasi rulare. Baza l-ar refuza pe al doilea (cheia primara ne
         apara), dar l-am fi numarat gresit ca "nou". Cifrele trebuie sa spuna adevarul.

    Ordinea se pastreaza: primul exemplar castiga, restul se ignora.
    """
    de_salvat = []
    vazute_acum = set()  # id-urile intalnite in chiar aceasta lista

    for mail in mailuri:
        id_mail = mail.get("id")

        # Un mail fara id nu poate fi salvat (id-ul e cheia primara in baza) si nu
        # poate fi recunoscut la rularea urmatoare. Il sarim, nu il inventam.
        if not id_mail:
            continue

        if id_mail in id_uri_existente:
            continue  # il avem din alta rulare

        if id_mail in vazute_acum:
            continue  # a aparut de doua ori chiar in citirea asta

        vazute_acum.add(id_mail)
        de_salvat.append(mail)

    return de_salvat
