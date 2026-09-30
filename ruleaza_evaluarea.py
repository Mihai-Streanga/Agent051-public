r"""
Evalueaza calitativ anunturile trecute de filtrul dur, cu modelul. COSTA BANI.

Rulare, din folderul proiectului:

    # DRY RUN (implicit): arata cate anunturi ar evalua si cat ar costa,
    # dar NU cheama modelul si nu cheltuie nimic.
    .\.venv\Scripts\python.exe ruleaza_evaluarea.py

    # cel mult 20 de anunturi, tot dry run:
    .\.venv\Scripts\python.exe ruleaza_evaluarea.py --limita 20

    # PE BUNE: cheama modelul, cheltuie bani. Fara --confirma nu se intampla.
    .\.venv\Scripts\python.exe ruleaza_evaluarea.py --confirma

    # REEVALUARE: trimite la model si ce are deja verdict valabil. Pentru cand ai
    # schimbat promptul fara sa urci versiunea criteriilor. Costa de la capat.
    .\.venv\Scripts\python.exe ruleaza_evaluarea.py --reevalueaza --confirma

CE NU SE MAI EVALUEAZA A DOUA OARA: un anunt care are deja un verdict trecut de validare,
dat pe versiunea de criterii de acum. Ar fi acelasi raspuns, platit inca o data. Se
reevalueaza singure cele de pe criterii vechi, cele a caror incercare a fost respinsa si
cele care au capatat DESCRIERE dupa ce primisera verdictul - alea fusesera judecate pe
titlu gol, deci raspunsul chiar se poate schimba. Ultimele se numara separat in raport.

DE CE dry run implicit: acelasi motiv ca la normalizare - un apel de model costa, iar o
rulare scapata ar da sute de apeluri. Prima rulare doar arata ce ar face; abia cu
--confirma se atinge modelul.

Ordinea normala a fluxului: intai ruleaza_normalizarea.py, apoi filtreaza (prin MCP sau
ruleaza), abia apoi asta - la evaluare ajung doar anunturile care au trecut filtrul dur.

Fisierul asta e doar linia de comanda. Nicio logica de business aici.
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
from agent051.adapters.evaluare_calitativa import ruleaza_evaluarea_calitativa
from agent051.adapters.model import EroareInfrastructura

# Estimare GROSIERA de cost pentru dry run - vezi aceeasi nota din ruleaza_normalizarea.py.
# Promptul de evaluare e mai lung decat cel de normalizare (contine si criteriile), deci
# presupunem mai multi tokeni de intrare. Cifrele reale se vad dupa o rulare adevarata.
# Preturile nu stau aici: vin din config/cost.yaml.
TOKENI_INTRARE_PE_APEL = 700
TOKENI_IESIRE_PE_APEL = 200


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evalueaza calitativ anunturile trecute de filtru. Implicit: dry run."
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
    parser.add_argument(
        "--reevalueaza",
        action="store_true",
        help=(
            "Reevalueaza si anunturile care au deja un verdict valabil pe criteriile "
            "de acum. De folosit cand ai schimbat PROMPTUL fara sa urci versiunea "
            "criteriilor. COSTA - implicit oprit."
        ),
    )
    argumente = parser.parse_args()

    dry_run = not argumente.confirma

    if dry_run:
        print("DRY RUN - nu se cheama modelul, nu se cheltuie nimic.\n")
    else:
        print("RULARE PE BUNE - se cheama modelul, COSTA bani.\n")

    # Pre-flight (biblioteca/cheie lipsa) iese ca EroareInfrastructura inainte sa se atinga
    # vreun anunt. O prindem si dam mesajul clar - nu o lasam sa para o respingere.
    if argumente.reevalueaza:
        print(
            "  REEVALUARE CERUTA: se trimit la model si anunturile care au deja un\n"
            "  verdict valabil pe criteriile de acum.\n"
        )

    try:
        raport = ruleaza_evaluarea_calitativa(
            limita=argumente.limita,
            dry_run=dry_run,
            reevalueaza=argumente.reevalueaza,
        )
    except EroareInfrastructura as eroare:
        print(f"  ESUAT (infrastructura): {eroare}")
        print("\n  Niciun anunt n-a fost atins. Repara asta si ruleaza din nou.")
        return 1

    # Defalcarea pe motive, nu doar totalul: "ar evalua 1 din 83" nu se poate verifica
    # daca nu vezi si ca 51 au fost respinse de filtru, iar 31 erau deja evaluate.
    print(f"  Anunturi candidate:              {raport['candidate']}")
    print(f"  Sarite - respinse de filtrul dur: {raport['sarite_respins']}")
    print(
        f"  Sarite - evaluate deja pe criteriile de acum: {raport['sarite_evaluate_deja']}"
        + ("  (ignorat, s-a cerut reevaluare)" if raport["reevalueaza"] else "")
    )
    if raport["rejudecate_descriere_noua"]:
        print(
            f"  Rejudecate - au capatat descriere dupa verdict: "
            f"{raport['rejudecate_descriere_noua']}"
        )
    print(f"  Au nevoie de model:              {raport['de_procesat']}")
    print(f"  Plafon (--limita):               {raport['limita']}")

    ar_procesa = min(raport["de_procesat"], raport["limita"])

    if dry_run:
        print(f"\n  AR EVALUA:               {ar_procesa} anunturi")
        if raport["sarite_evaluate_deja"] and not raport["reevalueaza"]:
            print(
                f"  (nu si cele {raport['sarite_evaluate_deja']} deja evaluate - "
                "ruleaza cu --reevalueaza daca ai schimbat promptul)"
            )
        if raport["oprite_de_limita"]:
            print(
                f"  Peste plafon, pe alta data: {raport['oprite_de_limita']} "
                "(ridica --limita ca sa le prinzi)"
            )
        estimare = estimare_usd(ar_procesa, TOKENI_INTRARE_PE_APEL, TOKENI_IESIRE_PE_APEL)
        print(f"\n  Cost estimat (grosier):  ~{in_dolari(estimare)}")
        print("\n  Ca sa rulezi pe bune, adauga --confirma.")
        return 0

    # Doua sectiuni DISTINCTE: ce a raspuns modelul fata de ce n-a ajuns la model.
    print(f"\n  EVALUATE:                {raport['evaluate']} anunturi")
    print(f"    valide (ok):           {raport['ok']}")
    print(f"    respinse de validare:  {raport['respinse_model']}  (modelul a raspuns, raspuns prost)")
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

    if raport["esec_infrastructura"]:
        print(f"\n  RULARE OPRITA (infrastructura): {raport['esec_infrastructura']}")
        print("  Anunturile neatinse NU au fost marcate - raman de reincercat.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
