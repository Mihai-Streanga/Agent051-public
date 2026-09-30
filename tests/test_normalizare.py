r"""
Teste pentru core/normalizare.py - cele doua functii PURE.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

Aici se testeaza capetele lantului: construirea promptului si validarea raspunsului.
Lantul intreg (prompt -> model -> validare) are testele lui separate, in
tests/test_adaptor_normalizare.py, fiindca orchestrarea sta in adapters/.

UITA-TE CE NU E AICI.
Nicio functie injectata, niciun model nici macar inventat. Fisierul asta da niste
siruri de caractere unor functii si verifica ce iese. Atat. Nu exista nimic de
"pregatit" inainte si nimic de curatat dupa.

CE VERIFICA, DE FAPT, FIECARE TEST DE MAI JOS:
ca un raspuns prost NU trece de valideaza() deghizat in raspuns bun.
Asta e singura intrebare care conteaza aici. Un model care raspunde aiurea din cand
in cand e normal si se poate reincerca. Un rand in baza care arata corect dar e
inventat nu se mai poate deosebi niciodata de unul real - si va fi folosit ca daca
ar fi adevarat, la evaluare si la generarea CV-ului.
"""

import sys
import unittest
from pathlib import Path

# Codul proiectului sta in src/. Ii aratam lui Python calea.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.core.normalizare import (
    CAMPURI_OBLIGATORII,
    construieste_prompt,
    valideaza,
)

ANUNT = {
    "titlu": "Specialist Payroll (m/f/d) - URGENT!!",
    "firma": "Firma Inventata SRL",
    "corp_text": "Cautam specialist salarizare, munca remote, 5 ani experienta.",
}

RASPUNS_BUN = """{
    "rol_normalizat": "Specialist Payroll",
    "senioritate": "senior",
    "tip_munca": "remote",
    "domeniu": "payroll"
}"""


# ---------------------------------------------------------------------------
# Felurile in care poate arata un raspuns prost. Sunt doar niste siruri de
# caractere, scrise ca functii ca sa aiba fiecare un nume care spune ce e stricat.
# ---------------------------------------------------------------------------

def model_cu_json_stricat(prompt: str = "") -> str:
    """A uitat o virgula intre campuri. Se intampla des si nu are voie sa crape nimic."""
    return """{
        "rol_normalizat": "Specialist Payroll"
        "senioritate": "senior",
        "tip_munca": "remote",
        "domeniu": "payroll"
    }"""


def model_fara_senioritate(prompt: str = "") -> str:
    """JSON perfect valid, dar ii lipseste un camp cerut."""
    return """{
        "rol_normalizat": "Specialist Payroll",
        "tip_munca": "remote",
        "domeniu": "payroll"
    }"""


def model_cu_senioritate_inventata(prompt: str = "") -> str:
    """A inventat o valoare care nu e in lista permisa: "expert"."""
    return """{
        "rol_normalizat": "Specialist Payroll",
        "senioritate": "expert",
        "tip_munca": "remote",
        "domeniu": "payroll"
    }"""


def model_politicos(prompt: str = "") -> str:
    """Raspunsul bun, dar impachetat in amabilitati si bloc de cod."""
    return (
        "Sigur! Iata analiza ceruta:\n\n```json\n"
        + RASPUNS_BUN
        + "\n```\n\nSper ca te ajuta!"
    )


class TestConstruiestePrompt(unittest.TestCase):

    def test_promptul_contine_datele_anuntului(self):
        """Ce stim despre anunt ajunge in cerere. Altfel modelul n-are ce judeca."""
        prompt = construieste_prompt(ANUNT)

        self.assertIn("Specialist Payroll", prompt)
        self.assertIn("Firma Inventata SRL", prompt)
        self.assertIn("munca remote", prompt)

    def test_promptul_cere_toate_campurile(self):
        """
        Fiecare camp pe care il validam trebuie si CERUT in prompt.

        Testul asta pare pedant, dar prinde o eroare foarte usor de facut: adaugi un
        camp nou in schema, uiti sa-l ceri in prompt, si de-atunci fiecare raspuns e
        respins pentru "lipseste campul X" - iar tu cauti vina in model.
        """
        prompt = construieste_prompt(ANUNT)

        for camp in CAMPURI_OBLIGATORII:
            self.assertIn(camp, prompt)

    def test_promptul_nu_cere_relevanta(self):
        """
        Normalizarea NU mai intreaba "e relevant?". Aici e gardul care tine asta.

        Campul a existat si a fost scos: modelul il dadea fara sa vada criteriile din
        criterii.yaml, deci raspundea generic - iar in baza ajungeau doua verdicte de
        relevanta, in doua tabele, raspunzand la aceeasi intrebare. Sursa unica e
        acum `evaluari_calitative.relevant`.

        Testul pare marunt, dar pazeste exact felul in care s-ar intoarce problema:
        cineva adauga la loc un camp in prompt, "ca oricum e ieftin", si peste o luna
        avem iar doua adevaruri.
        """
        prompt = construieste_prompt(ANUNT)

        self.assertNotIn("relevant", prompt)

    def test_anuntul_incomplet_nu_crapa(self):
        """Un anunt fara firma sau fara descriere tot produce un prompt utilizabil."""
        prompt = construieste_prompt({"titlu": "Payroll Officer"})

        self.assertIn("Payroll Officer", prompt)
        self.assertIn("(fara descriere)", prompt)

    def test_locatia_ajunge_in_prompt(self):
        """
        Locatia trebuie sa ajunga la model - multe anunturi (LinkedIn) pun felul muncii
        chiar acolo: "România (De la distanță)" = remote. Fara ea in prompt, modelul scrie
        "nespecificat", iar un remote real e tratat incert la filtru. Cerem si modelului,
        explicit, sa deduca tip_munca din locatie.
        """
        prompt = construieste_prompt(
            {"titlu": "HR Specialist", "locatie": "România (De la distanță)"}
        )

        self.assertIn("România (De la distanță)", prompt)
        # Instructiunea care leaga locatia de tip_munca trebuie sa fie in prompt.
        self.assertIn("tip_munca", prompt)
        self.assertIn("locatie", prompt.lower())


class TestValideaza(unittest.TestCase):

    def test_raspunsul_bun_e_acceptat(self):
        """Cazul normal: JSON curat, complet, cu valori din lista."""
        rezultat = valideaza(RASPUNS_BUN)

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["date"]["senioritate"], "senior")
        self.assertEqual(rezultat["date"]["rol_normalizat"], "Specialist Payroll")

    def test_json_stricat_e_respins_fara_sa_crape(self):
        """
        O virgula lipsa iese ca respingere, nu ca exceptie.

        Diferenta conteaza: o exceptie ar opri o rulare peste 300 de anunturi la
        primul raspuns prost. O respingere il marcheaza pe ala si merge mai departe.
        """
        rezultat = valideaza(model_cu_json_stricat(""))

        self.assertFalse(rezultat["ok"])
        self.assertIn("JSON invalid", rezultat["eroare"])

    def test_campul_lipsa_e_respins(self):
        """
        Fara `senioritate`, raspunsul e respins intreg.

        NU completam cu "nespecificat". Ar parea o gentilete, dar ar transforma o
        omisiune a modelului intr-o afirmatie a noastra - si peste doua luni n-ai mai
        sti care valori au fost spuse si care ghicite.
        """
        rezultat = valideaza(model_fara_senioritate(""))

        self.assertFalse(rezultat["ok"])
        self.assertIn("senioritate", rezultat["eroare"])

    def test_valoarea_inventata_e_respinsa(self):
        """
        "expert" nu e in lista permisa, deci raspunsul cade.

        Nu il traducem in "senior", desi ar fi ghicitul evident. Daca acceptam
        traduceri, lista permisa nu mai e o garantie, ci o sugestie - iar peste un an
        ai in baza valori pe care nu le-a cerut nimeni.
        """
        rezultat = valideaza(model_cu_senioritate_inventata(""))

        self.assertFalse(rezultat["ok"])
        self.assertIn("expert", rezultat["eroare"])

    def test_json_impachetat_in_text_e_extras_curat(self):
        """
        "Sigur! Iata:" + bloc de cod: desfacem ambalajul si acceptam continutul.

        Asta NU contrazice regula "nu reparam raspunsuri proaste". Continutul e
        intact - doar hartia din jur a fost data la o parte. Nu schimbam nicio valoare.
        """
        rezultat = valideaza(model_politicos(""))

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["date"]["tip_munca"], "remote")

    def test_raspunsul_gol_e_respins(self):
        """Nimic inauntru, nimic de validat."""
        for gol in ("", "   ", None):
            with self.subTest(raspuns=repr(gol)):
                rezultat = valideaza(gol)
                self.assertFalse(rezultat["ok"])

    def test_textul_fara_json_e_respins(self):
        """Modelul a raspuns in proza. Nu incercam sa citim printre randuri."""
        rezultat = valideaza("Nu pot analiza acest anunt, imi pare rau.")

        self.assertFalse(rezultat["ok"])

    def test_campul_text_gol_e_respins(self):
        """
        `rol_normalizat` prezent, dar gol, e ca si cum ar lipsi.

        Un camp obligatoriu completat cu "" trece de verificarea "exista?" fara sa
        spuna nimic. Il tratam ca lipsa - altfel ar fi o portita prin care raspunsuri
        vide intra in baza cu status "ok".
        """
        rezultat = valideaza(
            """{
                "rol_normalizat": "   ",
                "senioritate": "senior",
                "tip_munca": "remote",
                "domeniu": "payroll"
            }"""
        )

        self.assertFalse(rezultat["ok"])

    def test_campurile_in_plus_nu_intra_in_date(self):
        """
        Un camp pe care nu l-am cerut nu strica raspunsul, dar nici nu se salveaza.

        Schema e a noastra. Daca modelul mai adauga o parere pe langa, ramane afara.
        """
        rezultat = valideaza(
            """{
                "rol_normalizat": "Specialist Payroll",
                "senioritate": "senior",
                "tip_munca": "remote",
                "domeniu": "payroll",
                "salariu_estimat": 9000
            }"""
        )

        self.assertTrue(rezultat["ok"])
        self.assertNotIn("salariu_estimat", rezultat["date"])

    def test_json_care_nu_e_obiect_e_respins(self):
        """O lista e JSON valid, dar nu e ce am cerut."""
        rezultat = valideaza('["senior", "remote"]')

        self.assertFalse(rezultat["ok"])


if __name__ == "__main__":
    unittest.main()
