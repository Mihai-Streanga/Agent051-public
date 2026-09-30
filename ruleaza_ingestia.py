r"""
Citeste mailurile din folderul Joburi si le salveaza in baza de date.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe ruleaza_ingestia.py

    # doar cele mai recente 5 mailuri, ca sa incerci repede:
    .\.venv\Scripts\python.exe ruleaza_ingestia.py 5

Nu modifica nimic in Gmail: nu sterge, nu muta, nu marcheaza nimic ca citit.
Se poate rula de oricate ori - acelasi mail intra o singura data in baza.

Fisierul asta e doar linia de comanda: citeste argumentul, cheama orchestratorul
din adapters/ si afiseaza rezultatul. Nicio logica aici.
"""

import sys
from pathlib import Path

# Codul proiectului sta in src/, care nu e un loc unde Python cauta implicit.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent051.adapters.ingestie import ruleaza_ingestia


def _citeste_limita_din_argumente() -> int:
    """
    Daca ai scris un numar dupa numele scriptului, il folosim ca limita.
    Altfel, citim toate mailurile.
    """
    if len(sys.argv) < 2:
        return None
    try:
        return int(sys.argv[1])
    except ValueError:
        print(f"Argumentul '{sys.argv[1]}' nu e un numar. Il ignor, citesc tot.\n")
        return None


def main() -> int:
    limita = _citeste_limita_din_argumente()

    if limita:
        print(f"Citesc cele mai recente {limita} mailuri din Gmail...\n")
    else:
        print("Citesc mailurile din Gmail...\n")

    rezultat = ruleaza_ingestia(limita=limita)

    # Peste tot: MESAJE. Nu conversatii. Gmail iti arata in browser conversatii
    # (mesaje impaturite pe fire, cand au acelasi subiect), si de aceea cifra lui
    # e mult mai mica. Noi ingeram fiecare mesaj separat - fiecare are alte joburi.
    print("  INGESTIE TERMINATA  (unitate: MESAJE, nu conversatii)")
    print(f"  Vazute in Gmail:  {rezultat['citite']} mesaje")
    # Cate au fost DESCARCATE cu tot cu corp. Restul s-au recunoscut din antet, deci
    # n-au mai fost aduse - acolo se duceau cele 103 secunde de dinainte.
    print(f"  Descarcate:       {rezultat['aduse']} mesaje")
    print(f"  Noi, salvate:     {rezultat['noi']} mesaje")
    print(f"  Deja existente:   {rezultat['sarite']} mesaje")

    # Mesaje vechi carora tocmai le-am adaugat HTML-ul brut care lipsea.
    # Dupa prima re-ingestie, cifra asta va fi 0 la fiecare rulare.
    if rezultat.get("html_completat"):
        print(f"  HTML completat:   {rezultat['html_completat']} mesaje vechi")

    if rezultat["citite"] == 0:
        print(
            "\nNu am adus niciun mesaj. Verifica intai conexiunea:"
            "\n  .\\.venv\\Scripts\\python.exe verifica_gmail.py"
        )
        return 1

    print("\nGmail nu a fost modificat. Niciun mail nu a fost marcat ca citit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
