r"""
Verifica daca Agent 051 se poate conecta la Gmail.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe verifica_gmail.py

Nu citeste continutul niciunui mail. Doar se conecteaza, listeaza folderele si numara.

Fisierul asta e un ADAPTOR (interfata de linie de comanda). Rolul lui e sa apeleze
functia din ingest/ si sa afiseze rezultatul frumos. Nicio logica aici - daca ar
disparea, programul ar functiona la fel prin serverul MCP.

Nota: docstring-ul de mai sus incepe cu r-ul din r\"\"\" - un "raw string".
Fara el, Python vede "\.venv\Scripts" si incearca sa interpreteze \. si \S ca pe
niste secvente speciale (asa cum \n inseamna "linie noua"). Nu sunt, si de aceea
avertiza cu SyntaxWarning. Litera r ii spune: "ia backslash-urile ca atare".
"""

import sys
from pathlib import Path

# Codul proiectului sta in src/, care nu e un loc unde Python cauta implicit.
# Ii aratam calea, ca sa putem scrie "from agent051.ingest...".
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agent051.ingest.gmail import test_conexiune


def _afiseaza_folderele(foldere: list) -> None:
    """
    Afiseaza folderele exact cum le raporteaza serverul, cate unul pe rand.

    Nu prelucram nimic: numele afisat de Gmail in browser si numele real din IMAP
    pot sa difere (mai ales la etichetele imbricate si la folderele de sistem,
    care apar sub forma [Gmail]/...). Vrem sa vedem adevarul serverului, nu o
    varianta cosmetizata de noi.
    """
    if not foldere:
        print("  (serverul nu a raportat niciun folder)")
        return
    for folder in foldere:
        print(f"  {folder}")


def main() -> int:
    """Ruleaza verificarea si afiseaza rezultatul. Intoarce codul de iesire."""
    print("Verific conexiunea la Gmail...\n")

    rezultat = test_conexiune()

    # Lista de foldere exista ori de cate ori am apucat sa ne conectam - deci si
    # cand folderul cautat nu a fost gasit. O afisam intai, pentru ca tocmai atunci
    # e cea mai utila: iti arata cum se numeste de fapt eticheta.
    if "foldere" in rezultat:
        print("Foldere vazute de IMAP in cont:")
        _afiseaza_folderele(rezultat["foldere"])
        print()

    if rezultat["ok"]:
        print("  CONEXIUNE REUSITA")
        print(f"  Folder: {rezultat['folder']}")
        print()
        # Fiecare cifra isi spune unitatea de masura. Un numar fara unitate nu e o
        # informatie - iar aici, cele doua unitati chiar difera mult.
        print(f"  {rezultat['nr_mesaje']:>5} mesaje       "
              "<- asta ingereaza Agent 051 (cate unul, separat)")
        print(f"  {rezultat['nr_conversatii']:>5} conversatii  "
              "<- asta iti arata Gmail in browser (mesaje impaturite pe fire)")
        print()
        print("  Gmail grupeaza mesajele cu acelasi subiect intr-un singur fir.")
        print("  Zece alerte lunare de la BestJobs = 1 rand pe ecran, dar 10 mesaje")
        print("  reale, fiecare cu ALTE joburi in ea. Noi le vrem pe toate.")
        print("\nGata. Nu am deschis niciun mail.")
        return 0

    print("  CONEXIUNE ESUATA")
    print(f"  Motiv: {rezultat['eroare']}")
    return 1


if __name__ == "__main__":
    # Codul de iesire (0 = bine, 1 = eroare) e conventia prin care un program
    # ii spune sistemului de operare cum s-a terminat. Folositor mai tarziu,
    # cand verificarea va rula automat.
    sys.exit(main())
