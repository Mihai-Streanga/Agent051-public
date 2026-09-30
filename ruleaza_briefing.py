r"""
Arata ce s-a schimbat de la ultimul briefing.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe ruleaza_briefing.py
    .\.venv\Scripts\python.exe ruleaza_briefing.py --marcheaza-citit

Fara internet si fara niciun apel catre vreun model: lucreaza pe ce e deja in baza.
Se poate rula de oricate ori - o citire nu schimba nimic.

DESPRE --marcheaza-citit:
fara el, briefingul doar SE UITA. Reperul temporal ramane pe loc, deci urmatoarea
rulare arata aceleasi lucruri, plus ce a mai aparut intre timp.
Cu el, reperul se muta la momentul acestei rulari: ce ai vazut acum nu mai apare
data viitoare. E singurul fel in care briefingul "consuma" ceva, si se cere explicit
tocmai ca sa nu se intample din greseala.

Fisierul asta e doar linia de comanda. Nicio logica aici.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent051.adapters.briefing import briefing


def main() -> int:
    optiuni = argparse.ArgumentParser(
        description="Briefing: ce s-a schimbat de la ultima citire."
    )
    optiuni.add_argument(
        "--marcheaza-citit",
        action="store_true",
        help="muta reperul temporal, ca data viitoare sa nu mai apara ce vezi acum",
    )
    argumente = optiuni.parse_args()

    rezultat = briefing(marcheaza_citit=argumente.marcheaza_citit)

    print()
    print(rezultat["text"])
    print()

    if rezultat["reper_mutat"]:
        print("  Reper mutat. Urmatorul briefing porneste de la momentul asta.")
    else:
        print("  Reperul NU a fost mutat (ruleaza cu --marcheaza-citit ca sa-l muti).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
