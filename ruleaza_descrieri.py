r"""
Completeaza descrierile lipsa, citind paginile publice ale anunturilor.

Rulare, din folderul proiectului:

    # DRY RUN (implicit): arata carui anunt i s-ar cere pagina si cat ar dura,
    # dar NU atinge nicio retea.
    .\.venv\Scripts\python.exe ruleaza_descrieri.py

    # cel mult 10 pagini, tot dry run:
    .\.venv\Scripts\python.exe ruleaza_descrieri.py --limita 10

    # PE BUNE: cere paginile de la eJobs si BestJobs. Fara --confirma nu se intampla.
    .\.venv\Scripts\python.exe ruleaza_descrieri.py --confirma

DE CE dry run implicit, cand aici nu se cheltuie bani: se cheltuie rabdarea unui server
care ne da continut gratis. O rulare scapata peste toata baza ar insemna sute de cereri
si, foarte probabil, o blocare meritata. Prima rulare doar iti arata ce ar face.

Fisierul asta e doar linia de comanda: citeste argumentele, cheama orchestratorul din
adapters/ si afiseaza rezultatul. Nicio logica de business aici - nici filtrul de varsta,
nici plafonul, nici alegerea surselor; alea traiesc in adaptor si se testeaza singure.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent051.adapters.descrieri import ruleaza_descrierile
from agent051.ingest.pagini import EroareRetea

# Etichetele omenesti pentru motivele de sarire din raport. Cheia tehnica
# ("sursa_fara_parser") e buna in cod; pe ecran vrei o propozitie.
ETICHETE_SARITE = {
    "sursa_fara_parser": "sursa fara parser (LinkedIn)",
    "fara_link": "fara link in baza",
    "au_deja_descriere": "au deja descriere",
    "pagina_deja_luata": "pagina deja luata",
    "prea_vechi": "prea vechi (peste pragul din criterii.yaml)",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Completeaza descrierile lipsa din paginile publice. Implicit: dry run."
    )
    parser.add_argument(
        "--limita",
        type=int,
        default=30,
        help="Maxim atatea pagini cerute intr-o rulare (implicit 30).",
    )
    parser.add_argument(
        "--confirma",
        action="store_true",
        help="Ruleaza pe bune (cere paginile). Fara el: doar dry run.",
    )
    argumente = parser.parse_args()

    dry_run = not argumente.confirma

    if dry_run:
        print("DRY RUN - nu se cere nicio pagina, nu se atinge nicio retea.\n")
    else:
        print("RULARE PE BUNE - se cer pagini de pe internet.\n")

    try:
        raport = ruleaza_descrierile(limita=argumente.limita, dry_run=dry_run)
    except EroareRetea as eroare:
        print(f"  ESUAT (retea): {eroare}")
        print("\n  Niciun anunt n-a fost atins. Repara asta si ruleaza din nou.")
        return 1

    print(f"  Anunturi in baza:        {raport['candidate']}")
    for cheie, cate in raport["sarite"].items():
        print(f"    sarite - {ETICHETE_SARITE.get(cheie, cheie):<42} {cate}")
    print(f"  Eligibile:               {raport['de_procesat']}")
    print(f"  Plafon (--limita):       {raport['limita']}")
    print(f"  Surse citite:            {', '.join(raport['surse_permise'])}")

    if dry_run:
        secunde = raport["ar_procesa"] * raport["pauza_secunde"]
        print(f"\n  AR CERE:                 {raport['ar_procesa']} pagini")
        if raport["oprite_de_limita"]:
            print(
                f"  Peste plafon, pe alta data: {raport['oprite_de_limita']} "
                "(ridica --limita ca sa le prinzi)"
            )
        print(
            f"  Durata estimata:         ~{secunde:.0f} secunde "
            f"(pauza de {raport['pauza_secunde']}s intre cereri)"
        )
        print("\n  Ca sa rulezi pe bune, adauga --confirma.")
        return 0

    # Doua sectiuni DISTINCTE, ca la normalizare: ce am aflat despre anunturi, fata de
    # ce n-a ajuns niciodata la o pagina.
    print(f"\n  PAGINI CERUTE:           {raport['cerute']}")
    print(f"    cu descriere:          {raport['cu_descriere']}")
    print(f"    anunt expirat (404):   {raport['expirate']}  (fapt despre anunt, salvat)")
    print(f"    interzise de robots:   {raport['interzise_robots']}")
    print(f"    pagina fara descriere: {raport['fara_descriere']}  (HTML salvat, parserul n-a gasit textul)")
    print(f"  ESUATE (retea):          {raport['esuate_retea']}  (pagina NU a fost citita)")

    if raport["oprite_de_limita"]:
        print(
            f"  Peste plafon, pe alta data: {raport['oprite_de_limita']} "
            "(mai ruleaza o data ca sa le prinzi)"
        )

    if raport["esec_retea"]:
        print(f"\n  RULARE OPRITA (retea): {raport['esec_retea']}")
        print("  Anunturile neatinse NU au fost marcate - raman de reincercat.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
