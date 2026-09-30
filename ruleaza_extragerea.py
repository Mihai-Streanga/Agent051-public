r"""
Sparge mesajele din baza in anunturi individuale.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe ruleaza_extragerea.py

Nu atinge Gmail-ul si nu are nevoie de internet: lucreaza pe datele deja salvate.
Se poate rula de oricate ori - acelasi anunt intra o singura data in baza.

Fisierul asta e doar linia de comanda. Nicio logica aici.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent051.adapters.extragere import ruleaza_extragerea


# Cum se numeste fiecare fel pe ecran. Cheile vin din core/esecuri.py.
NUME_FEL = {
    "de_verificat": "NERECUNOSCUTE - uita-te la ele",
    "alerta_fara_linkuri": "alerte fara link-uri per job (nimic de extras)",
    "nu_e_alerta": "mailuri care nu sunt alerte de joburi (normal)",
}

# Ordinea de afisare: intai ce cere atentie, la urma ce e normal.
ORDINEA_FELURILOR = ["de_verificat", "alerta_fara_linkuri", "nu_e_alerta"]


def _afiseaza_mesajele_fara_anunturi(mesaje: list) -> None:
    """
    Mesajele din care n-a iesit niciun anunt, grupate PE FEL, apoi pe sursa si subiect.

    Gruparea pe fel e tot rostul afisarii. Inainte, lista avea 52 de randuri care
    aratau toate la fel de nevinovat, si nimeni nu se mai uita la ele - deci un sablon
    schimbat s-ar fi pierdut acolo. Acum, ce cere atentie sta sus si e numit asa:
      - NERECUNOSCUTE -> fie o alerta cu sablon nou (parserul trebuie reparat),
        fie un tip de mail pe care nu-l stiam. Se lamureste uitandu-te o data.
      - alerte fara link-uri -> mailuri despre joburi din care chiar nu e nimic de
        luat (rezumate LinkedIn de tip "companiile au facut angajari").
      - restul -> bun venit, coduri PIN, "ai aplicat cu succes". Normal.
    """
    if not mesaje:
        print("  (niciunul)")
        return

    for fel in ORDINEA_FELURILOR:
        ale_felului = [m for m in mesaje if m["fel"] == fel]
        if not ale_felului:
            continue

        print(f"\n   {len(ale_felului)}x {NUME_FEL[fel]}:")
        grupate = Counter((m["sursa"], m["subiect"][:50]) for m in ale_felului)
        for (sursa, subiect), n in grupate.most_common():
            print(f"     {n:3}x  [{sursa}] {subiect}")


def main() -> int:
    print("Sparg mesajele in anunturi...\n")

    r = ruleaza_extragerea()

    print("  EXTRAGERE TERMINATA")
    print(f"  Mesaje procesate: {r['mesaje_procesate']}")
    print(f"  Mesaje reusite:   {r['mesaje_reusite']}")
    print(f"  Fara anunturi:    {r['mesaje_fara_anunturi']}"
          f"  (din care NERECUNOSCUTE: {r['de_verificat']})")
    print(f"  Incomplete:       {r['mesaje_incomplete']}"
          "  (au iesit anunturi, dar nu toate joburile din link-uri)")
    print()
    print(f"  Anunturi extrase: {r['anunturi_extrase']}  (cu tot cu repetari)")
    print(f"  Anunturi NOI:     {r['anunturi_noi']}  (au intrat in baza)")
    print(f"  Deja existente:   {r['anunturi_sarite']}  (acelasi job, alt mail)")

    print("\n  MESAJE DIN CARE NU A IESIT NICIUN ANUNT:")
    _afiseaza_mesajele_fara_anunturi(r["fara_anunturi"])

    # De ce cifra asta NU intoarce cod de eroare: "nerecunoscut" nu inseamna neaparat
    # stricat. Un mail de reclama nou pica tot aici, si e nevinovat. Il vezi, te uiti
    # o data, si fie repari parserul, fie adaugi tiparul in core/esecuri.py.
    if r["de_verificat"]:
        print(
            f"\n  ATENTIE: {r['de_verificat']} mesaje nerecunoscute. Daca subiectul lor "
            "seamana a alerta de joburi, sablonul platformei s-a schimbat."
        )

    if r["mesaje_incomplete"]:
        print(f"\n  ATENTIE: {r['mesaje_incomplete']} mesaje incomplete - parserul a pierdut joburi:")
        for m in r["incomplete"]:
            print(
                f"     [{m['sursa']}] {m['subiect'][:50]}  "
                f"{m['anunturi_extrase']} din {m['joburi_in_linkuri']}"
            )

    # Un parser care nu extrage NIMIC din tot arhivul nu e "un parser care n-a gasit
    # joburi" - e un parser stricat. Iesim cu eroare, zgomotos, ca sa nu treaca tacut
    # printr-o rulare automata.
    if r["mesaje_procesate"] > 0 and r["anunturi_extrase"] == 0:
        print("\n  EROARE: niciun anunt extras din niciun mesaj.")
        print("  Parserele sunt stricate sau sabloanele s-au schimbat complet.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
