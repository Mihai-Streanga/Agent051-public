"""
Orchestrarea extragerii: sparge mesajele din baza in anunturi individuale.

Coregrafia:
    1. citeste mesajele din baza                -> store/db.py       (disc)
    2. alege parserul potrivit dupa sursa       -> parse/            (pur)
    3. sparge mesajul in anunturi               -> parse/            (pur)
    4. salveaza anunturile noi                  -> store/db.py       (disc)
    5. RAPORTEAZA tot, inclusiv esecurile

Nu atinge Gmail-ul. Nu atinge reteaua deloc. Lucreaza pe date deja salvate, deci se
poate rula de oricate ori, oricand, si fara internet. Daca maine gasim un parser
gresit, il reparam si rulam iar - datele brute sunt intacte in tabela mailuri.

Zero AI. Spargerea unui mail in anunturi e citirea unei structuri, nu o judecata.
"""

from agent051.core.anonimizare import curata_subiectul
from agent051.core.esecuri import DE_VERIFICAT, ALERTA_FARA_LINKURI, felul_esecului
from agent051.parse import bestjobs, ejobs, linkedin
from agent051.parse.comun import EroareParser
from agent051.store.db import (
    acoperire_extractie,
    initializeaza_db,
    mesaje_de_procesat,
    salveaza_anunt,
)

# Fiecare sursa are parserul ei. Cand apare o platforma noua, se adauga o linie aici
# si un fisier in parse/. Nimic altceva nu se schimba.
PARSERE = {
    "ejobs": ejobs,
    "bestjobs": bestjobs,
    "linkedin": linkedin,
}


def _mesaj_fara_anunturi(sursa: str, subiect_brut: str, motiv: str) -> dict:
    """
    Un rand din lista mesajelor din care n-a iesit niciun anunt.

    SUBIECTUL BRUT INTRA SI NU IESE. Se foloseste o singura data, ca sa aflam FELUL
    mesajului (core/esecuri.py are nevoie de cuvintele intregi: din "Bun venit pe
    eJobs" curatarea taie tocmai "Bun"). In raport pleaca doar varianta curatata de
    date personale - subiectele astea contin nume de oameni si, unul din arhiva, un
    cod PIN.
    """
    return {
        "sursa": sursa,
        "subiect": curata_subiectul(subiect_brut),
        "fel": felul_esecului(subiect_brut),
        "motiv": motiv,
    }


def ruleaza_extragerea() -> dict:
    """
    Sparge toate mesajele din baza in anunturi. Intoarce un raport.

    Raportul spune, obligatoriu:
        mesaje_procesate     - cate mesaje am incercat
        mesaje_reusite       - din cate am scos macar un anunt
        mesaje_fara_anunturi - din cate n-a iesit niciun anunt
        de_verificat         - dintre ele, cate NU LE RECUNOASTEM. Trebuie sa fie 0.
        alerte_fara_linkuri  - dintre ele, cate erau despre joburi, dar fara link-uri
        mesaje_incomplete    - din cate au iesit anunturi, dar mai putine decat joburile
                               din link-uri. Trebuie sa fie 0.
        anunturi_extrase     - cate anunturi au iesit, cu tot cu repetari
        anunturi_noi         - cate au intrat efectiv in baza
        anunturi_sarite      - cate le aveam deja (acelasi job, alt mail)
        fara_anunturi        - lista, cu sursa, subiectul CURATAT, FELUL si motivul
        incomplete           - lista, cu sursa, subiectul CURATAT si cele doua cifre
        acoperire            - per sursa: cate anunturi au acum descriere si salariu

    DE CE nu se mai cheama "mesaje_esuate" si "esecuri":
    fiindca nu erau esecuri. Masurat pe toata arhiva, cele 52 de mesaje "esuate" erau
    bun-venituri, coduri PIN, confirmari de aplicare si notificari de puzzle-uri -
    mailuri care n-au fost niciodata alerte de joburi. Un nume care striga "esec" la
    fiecare rulare pentru ceva normal te invata sa nu te mai uiti la el; si atunci,
    cand apare esecul adevarat, nu-l vezi.

    SUBIECTUL DIN RAPORT E CURATAT DE DATE PERSONALE, cel din baza NU.
    Raportul asta pleaca din agent - JA.S.Mine il citeste si il poate afisa pe ecran. Iar
    subiectele mailurilor nu sunt scrise pentru noi: contin nume de persoane, si unul din
    arhiva contine un cod PIN. Trece deci prin core/anonimizare.py, care taie ce e sau ar
    putea fi personal. In tabela `mailuri` subiectul ramane BRUT, exact cum a venit: e
    data bruta, iar ingestia nu curata. Ce arunci la ingestie nu mai
    poti recupera; ce cureti la iesire se poate oricand recalcula altfel.

    DE CE raportam ACOPERIREA (descriere/salariu pe sursa):
    exact ca sa se vada cat de "vazator" a devenit filtrul dur. El cauta cuvinte in
    descriere si citeste salariul din salariu_brut - daca pe o sursa aceste campuri
    raman goale, filtrul ramane orb pe sursa aia, oricat de bine ar fi scris. Cifra
    o spune dintr-o privire; altfel ai crede ca merge peste tot si te-ai insela.

    DE CE raportam mesajele fara anunturi in detaliu, si nu doar numarul lor:
    un parser care extrage 0 anunturi din 50 de mesaje si spune "gata, succes" e mai
    periculos decat unul care crapa. Te lasa sa crezi ca n-au fost joburi, cand de fapt
    platforma si-a schimbat sablonul.

    DE CE fiecare mesaj primeste si un FEL (vezi core/esecuri.py):
    lista, singura, nu ajunge. Ea are 52 de randuri la fiecare rulare, si toate arata
    la fel de nevinovat. Daca maine LinkedIn schimba sablonul, alerta adevarata cade in
    aceeasi gramada si totalul face 53 - nimeni nu observa. Felul separa cauzele, iar
    `de_verificat` e cifra care are voie sa fie 0: astazi, pe toata arhiva, chiar e.
    Cand nu mai e, te uiti la randurile marcate asa.
    """
    initializeaza_db()

    mesaje = mesaje_de_procesat()

    anunturi_extrase = 0
    anunturi_noi = 0
    reusite = 0
    fara_anunturi = []
    incomplete = []

    for mesaj in mesaje:
        parser = PARSERE.get(mesaj["sursa"])
        if parser is None:
            # Sursa necunoscuta: nu avem parser. Nu ghicim cu unul de la alta platforma.
            fara_anunturi.append(
                _mesaj_fara_anunturi(
                    mesaj["sursa"] or "necunoscut",
                    mesaj["subiect"],
                    "nu exista parser pentru sursa asta",
                )
            )
            continue

        try:
            anunturi = parser.extrage(mesaj["corp_html"], mesaj["id"])
        except EroareParser as eroare:
            # Parserul a TIPAT. Nu il ascundem, nu il ignoram: il notam in raport,
            # cu subiectul mesajului, ca sa te poti uita chiar tu la mailul vinovat.
            fara_anunturi.append(
                _mesaj_fara_anunturi(eroare.sursa, mesaj["subiect"], eroare.motiv)
            )
            continue

        reusite += 1
        anunturi_extrase += len(anunturi)

        # Numaratoarea de control: cate joburi DISTINCTE arata link-urile mailului, fara
        # filtrele parserului. Mai multe decat a scos parserul = un job pierdut pe drum.
        lipsa = len(parser.joburi_din_linkuri(mesaj["corp_html"])) - len(anunturi)
        if lipsa > 0:
            incomplete.append({
                "sursa": mesaj["sursa"],
                "subiect": curata_subiectul(mesaj["subiect"]),
                "anunturi_extrase": len(anunturi),
                "joburi_in_linkuri": len(anunturi) + lipsa,
            })

        for a in anunturi:
            a_intrat = salveaza_anunt(
                id_anunt=a["id"],
                mesaj_id=mesaj["id"],
                sursa=a["sursa"],
                titlu=a["titlu"],
                firma=a["firma"],
                locatie=a["locatie"],
                link=a["link"],
                # Data anuntului = data mesajului din care a venit. E cea mai buna
                # aproximare pe care o avem: mailul nu spune cand a fost publicat
                # jobul, doar cand ne-a fost trimis.
                data_anunt=mesaj["data_primire"],
                descriere=a.get("descriere", ""),
                salariu_brut=a.get("salariu_brut", ""),
            )
            if a_intrat:
                anunturi_noi += 1

    return {
        "mesaje_procesate": len(mesaje),
        "mesaje_reusite": reusite,
        "mesaje_fara_anunturi": len(fara_anunturi),
        # Cifra care are voie sa fie 0, si care e singurul motiv sa te uiti in lista.
        "de_verificat": sum(1 for m in fara_anunturi if m["fel"] == DE_VERIFICAT),
        "alerte_fara_linkuri": sum(
            1 for m in fara_anunturi if m["fel"] == ALERTA_FARA_LINKURI
        ),
        # A doua cifra care are voie sa fie 0: mailuri din care au iesit anunturi, dar
        # nu toate. 0 pe toata arhiva la 29 septembrie 2026 (637 de mailuri).
        "mesaje_incomplete": len(incomplete),
        "anunturi_extrase": anunturi_extrase,
        "anunturi_noi": anunturi_noi,
        "anunturi_sarite": anunturi_extrase - anunturi_noi,
        "fara_anunturi": fara_anunturi,
        "incomplete": incomplete,
        # Numarat din baza DUPA extragere, peste toata arhiva - nu doar anunturile noi.
        # Asa cifra e reala chiar si la o re-rulare, cand anunturi_noi e 0 dar
        # backfill-ul tocmai a completat descriere/salariu pe randurile vechi.
        "acoperire": acoperire_extractie(),
    }
