r"""
Teste pentru adapters/model.py - singurul fisier care atinge un model.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

UITA-TE CE NU E AICI.
Niciun apel real catre model, nicio cheie adevarata, nicio retea. Apelul propriu-zis
(_apeleaza_modelul) e inlocuit cu o functie inventata unde ne trebuie - exact ca modelele
injectate din celelalte suite. Verificam DOAR logica din jurul apelului: pre-flight-ul
care opreste o rulare fara cheie, si contorul care numara corect.
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent051.adapters.model as model
from agent051.adapters.model import (
    ContorCost,
    EroareInfrastructura,
    RaspunsTaiat,
    construieste_cheama_model,
    verifica_infrastructura,
)


class TestPreFlight(unittest.TestCase):
    """
    Pre-flight-ul opreste o rulare reala INAINTE sa atinga vreun anunt, daca lipseste
    cheia. Asa, o cheie uitata nu se mai preface in "50 de anunturi respinse".
    """

    def test_cheie_lipsa_ridica_eroare_de_infrastructura(self):
        """
        Fara ANTHROPIC_API_KEY, pre-flight-ul ridica EroareInfrastructura cu mesaj clar.

        Punem cheia goala direct in mediu; load_dotenv (fara override) n-o suprascrie, deci
        testul da acelasi rezultat indiferent ce e in .env-ul masinii.
        """
        vechi = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = ""
        if vechi is None:
            self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        else:
            self.addCleanup(os.environ.__setitem__, "ANTHROPIC_API_KEY", vechi)

        with self.assertRaises(EroareInfrastructura) as capcana:
            verifica_infrastructura()

        self.assertIn("ANTHROPIC_API_KEY", str(capcana.exception))

    def _pune_in_mediu(self, nume: str, valoare: str):
        """Pune o variabila in mediu pe durata testului; load_dotenv n-o suprascrie."""
        vechi = os.environ.get(nume)
        os.environ[nume] = valoare
        if vechi is None:
            self.addCleanup(os.environ.pop, nume, None)
        else:
            self.addCleanup(os.environ.__setitem__, nume, vechi)

    def test_model_lipsa_ridica_eroare_de_infrastructura(self):
        """
        Fara MODEL_NORMALIZARE, rularea se opreste - nu cade tacut pe alt model.
        Pana la 30 sept. 2026, lipsa lui aducea un Haiku, adica alt judecator.
        """
        self._pune_in_mediu("ANTHROPIC_API_KEY", "cheie-inventata")
        self._pune_in_mediu("MODEL_NORMALIZARE", "")

        with self.assertRaises(EroareInfrastructura) as capcana:
            verifica_infrastructura()

        self.assertIn("MODEL_NORMALIZARE", str(capcana.exception))

    def test_model_lipsa_se_citeste_ca_None(self):
        self._pune_in_mediu("MODEL_NORMALIZARE", "  ")
        self.assertIsNone(model.model_configurat())


class TestContor(unittest.TestCase):
    """
    Contorul numara apelurile si tokenii. Il testam inlocuind apelul propriu-zis cu o
    functie inventata - fara retea, fara cheie.
    """

    def test_tokeni_total_aduna_intrare_si_iesire(self):
        contor = ContorCost()
        contor.tokeni_intrare = 30
        contor.tokeni_iesire = 12
        self.assertEqual(contor.tokeni_total, 42)

    def test_un_apel_reusit_se_numara_in_contor(self):
        """
        cheama_model construit cu contor: dupa un apel reusit, aduna 1 apel si tokenii lui.
        """
        contor = ContorCost()
        original = model._apeleaza_modelul
        model._apeleaza_modelul = lambda prompt: ("raspunsul modelului", 100, 40)
        try:
            cheama = construieste_cheama_model(contor)
            text = cheama("un prompt")
        finally:
            model._apeleaza_modelul = original

        self.assertEqual(text, "raspunsul modelului")
        self.assertEqual(contor.apeluri, 1)
        self.assertEqual(contor.tokeni_intrare, 100)
        self.assertEqual(contor.tokeni_iesire, 40)

    def test_un_apel_care_pica_NU_se_numara(self):
        """
        Un apel care pica (retea, cheie respinsa) nu a consumat nimic facturabil, deci nu
        se numara. Incrementarea se face DUPA ce apelul a reusit - vezi construieste_cheama_model.
        """
        contor = ContorCost()
        original = model._apeleaza_modelul

        def pica(prompt):
            raise EroareInfrastructura("retea cazuta")

        model._apeleaza_modelul = pica
        try:
            cheama = construieste_cheama_model(contor)
            with self.assertRaises(EroareInfrastructura):
                cheama("un prompt")
        finally:
            model._apeleaza_modelul = original

        self.assertEqual(contor.apeluri, 0)
        self.assertEqual(contor.tokeni_intrare, 0)
        self.assertEqual(contor.tokeni_iesire, 0)

    def test_un_raspuns_taiat_SE_numara_si_trece_mai_departe(self):
        """
        Un raspuns taiat la limita a fost scris de model, deci e facturat: se numara.
        Eroarea nu se inghite - trece la adaptor, care opreste rularea.
        """
        contor = ContorCost()
        original = model._apeleaza_modelul

        def taie(prompt):
            raise RaspunsTaiat(100, model.MAX_TOKENI)

        model._apeleaza_modelul = taie
        try:
            cheama = construieste_cheama_model(contor)
            with self.assertRaises(RaspunsTaiat):
                cheama("un prompt")
        finally:
            model._apeleaza_modelul = original

        self.assertEqual(contor.apeluri, 1)
        self.assertEqual(contor.tokeni_intrare, 100)
        self.assertEqual(contor.tokeni_iesire, model.MAX_TOKENI)


def _raspuns_inventat(stop_reason: str, text: str = '{"a": 1}'):
    """Un raspuns cu forma celui din biblioteca `anthropic`, fara biblioteca si fara retea."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=200, output_tokens=30),
        stop_reason=stop_reason,
    )


class TestRaspunsTaiat(unittest.TestCase):
    """
    Un raspuns oprit de limita de lungime nu e o parere a modelului despre anunt. Daca ar
    ajunge la validare, JSON-ul taiat ar iesi "respins" - o minciuna in baza.
    """

    def test_raspunsul_terminat_normal_trece(self):
        rezultat = model._rezultat_din_raspuns(_raspuns_inventat("end_turn"))
        self.assertEqual(rezultat, ('{"a": 1}', 200, 30))

    def test_raspunsul_oprit_de_limita_ridica_RaspunsTaiat(self):
        with self.assertRaises(RaspunsTaiat) as capcana:
            model._rezultat_din_raspuns(_raspuns_inventat("max_tokens", '{"a": '))

        self.assertEqual(capcana.exception.tokeni_intrare, 200)
        self.assertEqual(capcana.exception.tokeni_iesire, 30)
        self.assertIn("taiat", str(capcana.exception))

    def test_RaspunsTaiat_e_prins_ca_esec_de_infrastructura(self):
        """
        Adaptoarele prind EroareInfrastructura: asa opresc rularea fara sa atinga anuntul.
        RaspunsTaiat trebuie prins de acelasi `except`, fara ca adaptoarele sa-l stie.
        """
        self.assertTrue(issubclass(RaspunsTaiat, EroareInfrastructura))

    def test_limita_lasa_loc_pentru_gandirea_modelului(self):
        """
        La 1024, gandirea lui Sonnet 5 plus trei verdicte motivate n-au incaput: rularea
        din 29 septembrie 2026 s-a oprit la a treia evaluare. Limita nu se coboara inapoi
        fara o masuratoare noua.
        """
        self.assertGreaterEqual(model.MAX_TOKENI, 4096)


if __name__ == "__main__":
    unittest.main()
