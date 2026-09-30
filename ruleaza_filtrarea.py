r"""
Trece anunturile normalizate prin constrangerile dure din criterii.yaml.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe ruleaza_filtrarea.py

Determinist, fara model si fara internet - deci NU are dry run si NU are --confirma.
Un filtru pe reguli da acelasi raspuns de fiecare data si nu costa nimic; nu e nimic de
simulat inainte. Se ruleaza direct, si mai ales dupa fiecare modificare a lui
criterii.yaml: schimbi un prag, rulezi iar, ai verdictele noi in cateva secunde.

Fisierul asta e doar linia de comanda: cheama orchestratorul din adapters/ si afiseaza
rezultatul. Nicio logica aici - "trece sau nu" se decide in core/filtrare.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent051.adapters.filtrare import ruleaza_filtrarea


def _afiseaza_grupat(titlu: str, contoare: dict) -> None:
    """
    O harta motiv -> de cate ori a aparut, cele mai frecvente primele.

    DE CE le aratam, nu doar numarul total: "180 respinse" nu-ti spune nimic si te face
    sa ai incredere degeaba. "174 pentru cuvantul 'ture'" iti spune imediat daca regula
    aia taie prea lat - un filtru determinist gresit taie tacut si consecvent, deci
    trebuie sa se vada PE CE taie, nu doar cat.
    """
    print(f"\n  {titlu}")
    if not contoare:
        print("    (niciunul)")
        return
    for motiv, n in contoare.items():
        print(f"    {n:4}x  {motiv}")


def main() -> int:
    print("Filtrez anunturile normalizate pe constrangerile dure...\n")

    r = ruleaza_filtrarea()

    print("  FILTRARE TERMINATA")
    print(f"  Anunturi procesate: {r['anunturi_evaluate']}")
    print(f"  Trec:               {r['trecute']}")
    print(f"  Respinse:           {r['respinse']}  (au incalcat o constrangere dura)")
    print(f"  Incerte:            {r['incerte']}  (nimic incalcat, dar date lipsa)")
    print(f"  Versiune criterii:  {r['versiune_criterii']}")

    _afiseaza_grupat("Motive de respingere:", r["motive_frecvente"])
    _afiseaza_grupat("Date lipsa (de ce unele raman incerte):", r["lipsuri_frecvente"])

    # Filtrul lucreaza doar pe anunturi normalizate cu succes. Zero procesate cu anunturi
    # in baza inseamna ca normalizarea n-a rulat inca - nu e o eroare a filtrului.
    if r["anunturi_evaluate"] == 0:
        print(
            "\n  Zero anunturi procesate. Filtrul lucreaza doar pe cele normalizate -"
            "\n  ruleaza intai normalizarea:  .\\.venv\\Scripts\\python.exe ruleaza_normalizarea.py --confirma"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
