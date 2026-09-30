"""
O singura regula despre varsta unui anunt, folosita peste tot unde conteaza.

DE CE EXISTA FISIERUL ASTA: aceeasi functie de opt randuri a trait, pana pe 16 august
2026, in trei copii - in adapters/normalizare.py, adapters/descrieri.py si
adapters/briefing.py. Nu din neglijenta: briefingul nu avea de unde s-o importe fara sa
depinda, la import, de plumbaria modelului si a retelei, adica exact lucrul pe care
antetul lui spune ca nu-l face. Locul corect era de la inceput un fisier pur; capitolul
de curatenie l-a facut.

Si conteaza sa fie una singura, nu doar sa fie frumos: briefingul anunta "mai sunt 25
nenormalizate", iar rularea de normalizare decide singura pe cine ia. Daca cele doua
raspunsuri s-ar desparti, avertizarea ar deveni fix genul de cifra pe care n-o poti
verifica - si pe care, dupa o vreme, n-o mai crede nimeni.

Fisierul e pur: singurul import e `datetime`, din Python. `acum` se primeste ca
parametru, nu se citeste ceasul aici - asa aceeasi baza da acelasi raspuns la doua
rulari de test.
"""

from datetime import datetime, timedelta, timezone


def este_recent(data_anunt: str, acum: datetime, zile: int) -> bool:
    """
    Spune daca un anunt e mai nou de `zile` fata de `acum`. Fara data valida -> NU.

    `data_anunt` e data mesajului din care a venit anuntul, in ISO 8601. O transformam
    intr-un moment real ca sa comparam corect - doua texte ISO comparate ca text mint
    cand fusurile orare difera (vezi aceeasi explicatie la _data_din_text din
    store/db.py).

    Un anunt fara data, sau cu data stricata, iese "nu e recent". Cand nu stim varsta,
    nu ghicim in favoarea noastra, si asta costa acelasi lucru in toate cele trei
    locuri de unde se cheama: la normalizare ar fi un apel de model platit pe un anunt
    care ar putea fi din 2015; la descrieri, o cerere aruncata catre o pagina aproape
    sigur moarta si un 404 in plus in raport; la briefing, o avertizare umflata cu
    munca pe care nimeni n-o va face vreodata.
    """
    if not data_anunt:
        return False
    try:
        moment = datetime.fromisoformat(data_anunt)
    except (TypeError, ValueError):
        return False

    # Data fara fus declarat: presupunem UTC, altfel Python refuza comparatia cu un
    # moment "cu fus".
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    return moment >= acum - timedelta(days=zile)
