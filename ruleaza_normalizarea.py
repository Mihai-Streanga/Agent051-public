r"""
Normalizeaza anunturile recente cu ajutorul modelului. COSTA BANI.

Rulare, din folderul proiectului:

    # DRY RUN (implicit): arata cate anunturi ar procesa si cat ar costa,
    # dar NU cheama modelul si nu cheltuie nimic.
    .\.venv\Scripts\python.exe ruleaza_normalizarea.py

    # cel mult 20 de anunturi, tot dry run:
    .\.venv\Scripts\python.exe ruleaza_normalizarea.py --limita 20

    # PE BUNE: cheama modelul, cheltuie bani. Fara --confirma nu se intampla.
    .\.venv\Scripts\python.exe ruleaza_normalizarea.py --confirma

DE CE dry run implicit: un apel de model costa, iar o rulare scapata peste toata baza
ar da sute de apeluri fara sa vrei. Asa, prima rulare doar iti arata ce ar face; abia
cu --confirma se atinge modelul.

Fisierul asta e doar linia de comanda: citeste argumentele, cheama orchestratorul din
adapters/ si afiseaza rezultatul. Nicio logica de business aici - nici macar filtrul de
varsta sau plafonul, alea traiesc in adaptor si se testeaza singure.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent051.adapters.consum import (
    estimare_usd,
    in_dolari,
    rand_despre_luna,
    situatia_lunii_curente,
)
from agent051.adapters.model import EroareInfrastructura
from agent051.adapters.normalizare import ruleaza_normalizarea

# Estimare GROSIERA de cost pentru dry run. NU e o factura - e un ordin de marime, ca sa
# stii daca "50 de apeluri" inseamna centi sau zeci de lei inainte sa apesi --confirma.
# Presupunem un anunt scurt; preturile vin din config/cost.yaml. Cifrele reale se vad
# DUPA o rulare adevarata, in raport si in stare_pipeline.
TOKENI_INTRARE_PE_APEL = 400
TOKENI_IESIRE_PE_APEL = 120


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalizeaza anunturile recente cu modelul. Implicit: dry run."
    )
    parser.add_argument(
        "--limita",
        type=int,
        default=50,
        help="Maxim atatea apeluri de model intr-o rulare (implicit 50).",
    )
    parser.add_argument(
        "--confirma",
        action="store_true",
        help="Ruleaza pe bune (cheama modelul, costa). Fara el: doar dry run.",
    )
    argumente = parser.parse_args()

    dry_run = not argumente.confirma

    if dry_run:
        print("DRY RUN - nu se cheama modelul, nu se cheltuie nimic.\n")
    else:
        print("RULARE PE BUNE - se cheama modelul, COSTA bani.\n")

    # Pre-flight (biblioteca lipsa, cheie lipsa) iese ca EroareInfrastructura INAINTE sa
    # se atinga vreun anunt. O prindem aici si dam mesajul clar, cu cod de eroare - nu o
    # lasam sa se prefaca in "50 de anunturi respinse".
    try:
        raport = ruleaza_normalizarea(limita=argumente.limita, dry_run=dry_run)
    except EroareInfrastructura as eroare:
        print(f"  ESUAT (infrastructura): {eroare}")
        print("\n  Niciun anunt n-a fost atins. Repara asta si ruleaza din nou.")
        return 1

    print(f"  Anunturi in baza:        {raport['candidate']}")
    print(f"  Sarite (prea vechi):     {raport['sarite_vechi']}")
    print(f"  Sarite (deja normalizate): {raport['sarite_deja_normalizate']}")
    if raport["renormalizate_descriere_noua"]:
        print(
            f"  Renormalizate (descriere aparuta dupa): "
            f"{raport['renormalizate_descriere_noua']}"
        )
    print(f"  Eligibile (recente, noi):  {raport['de_procesat']}")
    print(f"  Plafon (--limita):         {raport['limita']}")

    if dry_run:
        print(f"\n  AR PROCESA:              {raport['ar_procesa']} anunturi")
        if raport["oprite_de_limita"]:
            print(
                f"  Peste plafon, pe alta data: {raport['oprite_de_limita']} "
                "(ridica --limita ca sa le prinzi)"
            )
        estimare = estimare_usd(
            raport["ar_procesa"], TOKENI_INTRARE_PE_APEL, TOKENI_IESIRE_PE_APEL
        )
        print(f"\n  Cost estimat (grosier):  ~{in_dolari(estimare)}")
        print("\n  Ca sa rulezi pe bune, adauga --confirma.")
        return 0

    # Doua sectiuni DISTINCTE: ce a raspuns modelul (si a fost bun sau prost) fata de ce
    # n-a ajuns niciodata la model. Nu se mai confunda.
    print(f"\n  PROCESATE:               {raport['procesate']} anunturi")
    print(f"    valide (ok):           {raport['ok']}")
    print(f"    respinse de validare:  {raport['respinse']}  (modelul a raspuns, raspuns prost)")
    print(f"  ESUATE (infrastructura): {raport['esuate_infrastructura']}  (modelul NU a fost chemat)")

    if raport["oprite_de_limita"]:
        print(
            f"  Peste plafon, pe alta data: {raport['oprite_de_limita']} "
            "(mai ruleaza o data ca sa le prinzi)"
        )

    cost = raport["cost"]
    print(
        f"\n  Cost real: {cost['apeluri']} apeluri, "
        f"{cost['tokeni_intrare']} tokeni intrare + "
        f"{cost['tokeni_iesire']} tokeni iesire = {in_dolari(cost['cost_usd'])}."
    )
    print(f"  {rand_despre_luna(situatia_lunii_curente())}")

    # Esec de infrastructura la mijloc de lot (ex: cheie respinsa la primul apel): oprit,
    # anunturile neatinse raman de reincercat. Iesim cu cod de eroare, ca sa se vada.
    if raport["esec_infrastructura"]:
        print(f"\n  RULARE OPRITA (infrastructura): {raport['esec_infrastructura']}")
        print("  Anunturile neatinse NU au fost marcate - raman de reincercat.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
