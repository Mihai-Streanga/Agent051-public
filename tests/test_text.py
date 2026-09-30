r"""
Teste pentru core/text.py - functia unica de scos diacriticele.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

CE VERIFICA: ca toate felurile in care datele scriu aceeasi litera ajung la aceeasi
forma. Functia era inainte scrisa de doua ori, cu rezultate usor diferite; testele de
aici tin minte ce trebuie sa faca, ca sa nu se mai desparta.
"""

import sys
import unittest
from pathlib import Path

# Codul proiectului sta in src/. Ii aratam lui Python calea.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.core.text import fara_diacritice


class TestFaraDiacritice(unittest.TestCase):

    def test_literele_romanesti_devin_simple(self):
        self.assertEqual(fara_diacritice("ăâîșțĂÂÎȘȚ"), "aaistaaist")

    def test_s_cu_virgula_si_s_cu_sedila_sunt_aceeasi_litera(self):
        # "ș" (virgula, U+0219) si "ş" (sedila, U+015F) arata la fel pe ecran.
        self.assertEqual(fara_diacritice("Brașov"), "brasov")
        self.assertEqual(fara_diacritice("Braşov"), "brasov")

    def test_majusculele_devin_litere_mici(self):
        self.assertEqual(fara_diacritice("BRAȘOV"), "brasov")

    def test_caracterele_de_compatibilitate_ajung_la_forma_simpla(self):
        # Ligatura "ﬁ" si spatiul care nu se rupe apar in mailuri copiate din PDF-uri.
        self.assertEqual(fara_diacritice("ﬁnance"), "finance")
        self.assertEqual(fara_diacritice("on call"), "on call")

    def test_textul_gol_ramane_gol(self):
        self.assertEqual(fara_diacritice(""), "")

    def test_lipsa_textului_nu_e_ghicita(self):
        # Cine are un text care poate lipsi decide singur ce inseamna lipsa lui.
        with self.assertRaises(TypeError):
            fara_diacritice(None)


if __name__ == "__main__":
    unittest.main()
