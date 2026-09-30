r"""
Teste pentru core/esecuri.py.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

Ca la toate testele din core/: fara internet, fara baza de date, fara mailuri reale.
Doar niste subiecte scrise de mana si un raspuns verificat.

Subiectele de mai jos sunt SCURTATE si fara nume de persoane - in arhiva reala,
subiectele astea contin numele autorului si al altor oameni, iar fisierul asta e in
Git. Tiparele se verifica la fel de bine si asa: ce recunoaste functia sunt cuvintele
sablonului, nu numele destinatarului.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.core.esecuri import (
    ALERTA_FARA_LINKURI,
    DE_VERIFICAT,
    NU_E_ALERTA,
    felul_esecului,
)


class TestFelulEsecului(unittest.TestCase):

    def test_bun_venit_nu_e_alerta(self):
        self.assertEqual(felul_esecului("Bun venit pe eJobs"), NU_E_ALERTA)

    def test_confirmare_de_aplicare_nu_e_alerta(self):
        self.assertEqual(felul_esecului("Ai aplicat cu succes la acest job!"), NU_E_ALERTA)
        self.assertEqual(
            felul_esecului("You have successfully applied to the job!"), NU_E_ALERTA
        )

    def test_notificarile_de_joc_nu_sunt_alerte(self):
        self.assertEqual(
            felul_esecului("Aptitudine nouă disponibilă: Rezolvare de puzzle-uri 🧩"),
            NU_E_ALERTA,
        )

    def test_rezumatul_vechi_e_alerta_fara_linkuri(self):
        """
        Mailul asta E despre joburi - doar ca sablonul lui nu contine link-uri catre
        anunturi individuale, ci doar catre cautari. Nu e nimic de reparat in parser,
        dar nici nu e un simplu bun venit: sunt oportunitati pe care nu le vedem.
        """
        self.assertEqual(
            felul_esecului("companiile au făcut angajări pentru 181 de posturi"),
            ALERTA_FARA_LINKURI,
        )

    def test_indemnul_linkedin_spre_cautari_e_alerta_fara_linkuri(self):
        # Mailul real din 19 aug. 2026: preferinte de job si link-uri spre cautari, niciun job.
        self.assertEqual(
            felul_esecului("Ion Şerban, vă căutați un job nou?"),
            ALERTA_FARA_LINKURI,
        )

    def test_sablon_nou_de_alerta_cade_la_de_verificat(self):
        """
        ASTA E TESTUL PENTRU CARE EXISTA FISIERUL.

        Daca maine LinkedIn schimba sablonul, alerta adevarata nu mai are voie sa se
        piarda in gramada de mailuri nevinovate. Un subiect pe care nu-l recunoastem
        iese "de_verificat", oricat de banal ar arata.
        """
        self.assertEqual(felul_esecului("12 joburi noi pentru tine"), DE_VERIFICAT)
        self.assertEqual(
            felul_esecului("Payroll Specialist: 3 anunturi noi"), DE_VERIFICAT
        )

    def test_diacriticele_scrise_altfel_nu_schimba_raspunsul(self):
        """
        In arhiva reala, "s cu virgula" apare in doua variante Unicode diferite, care
        arata la fel pe ecran. Amandoua trebuie sa dea acelasi rezultat - altfel
        jumatate din mesaje ar scapa nerecunoscute, fara sa se vada de ce.
        """
        cu_virgula = felul_esecului("începeți o conversație cu noul dvs. contact")
        cu_sedila = felul_esecului("începeţi o conversaţie cu noul dvs. contact")
        self.assertEqual(cu_virgula, NU_E_ALERTA)
        self.assertEqual(cu_sedila, NU_E_ALERTA)

    def test_subiect_gol_e_de_verificat(self):
        """Despre un mail fara subiect nu stim nimic. Deci nu presupunem nimic."""
        self.assertEqual(felul_esecului(""), DE_VERIFICAT)
        self.assertEqual(felul_esecului("   "), DE_VERIFICAT)
        self.assertEqual(felul_esecului(None), DE_VERIFICAT)


if __name__ == "__main__":
    unittest.main()
