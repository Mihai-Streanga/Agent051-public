r"""
Teste pentru costul in bani: core/cost.py (pur) si contoarele lunare din store/db.py.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

Preturile se injecteaza: testele nu citesc config/cost.yaml, ca sa nu depinda de el.
Baza e temporara; data/agent051.db NU E ATINSA NICIODATA.
"""

import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.core.cost import cost_usd, situatia_lunii
from agent051.store import db

MODEL = "claude-haiku-4-5-20251001"
PRETURI = {
    "model": MODEL,
    "pret_intrare_usd_pe_milion": 1.0,
    "pret_iesire_usd_pe_milion": 5.0,
    "buget_lunar_usd": 5.0,
}
CONSUM = {"apeluri": 10, "tokeni_intrare": 1_000_000, "tokeni_iesire": 200_000}


class TestCostulInBani(unittest.TestCase):

    def test_intrarea_si_iesirea_au_preturi_diferite(self):
        # 1M intrare x 1$ + 0,2M iesire x 5$ = 1$ + 1$ = 2$
        self.assertEqual(cost_usd(1_000_000, 200_000, PRETURI, MODEL), 2.0)

    def test_situatia_lunii_da_procentul_din_buget(self):
        luna = situatia_lunii("2026-09", CONSUM, PRETURI, MODEL)

        self.assertEqual(luna["cost_usd"], 2.0)
        self.assertEqual(luna["buget_usd"], 5.0)
        self.assertEqual(luna["procent_din_buget"], 40.0)
        self.assertEqual(luna["apeluri"], 10)
        self.assertIn("JA.S.Mine", luna["nota"])

    def test_luna_fara_consum_costa_zero(self):
        gol = {"apeluri": 0, "tokeni_intrare": 0, "tokeni_iesire": 0}
        luna = situatia_lunii("2026-10", gol, PRETURI, MODEL)

        self.assertEqual(luna["cost_usd"], 0.0)
        self.assertEqual(luna["procent_din_buget"], 0.0)


class TestPreturileSeRespingNuSeRepara(unittest.TestCase):
    """Un pret lipsa, gresit sau al altui model nu da o cifra - da None, cu motiv."""

    def _verifica_respins(self, config, model, bucata_din_motiv):
        self.assertIsNone(cost_usd(100, 100, config, model))
        luna = situatia_lunii("2026-09", CONSUM, config, model)
        self.assertIsNone(luna["cost_usd"])
        self.assertIsNone(luna["procent_din_buget"])
        self.assertIn(bucata_din_motiv, luna["motiv"])
        # Tokenii se vad oricum: lipsa pretului nu ascunde consumul.
        self.assertEqual(luna["tokeni_intrare"], 1_000_000)

    def test_fisierul_lipsa(self):
        self._verifica_respins({}, MODEL, "config/cost.yaml")

    def test_pretul_care_nu_e_numar(self):
        self._verifica_respins(
            {**PRETURI, "pret_iesire_usd_pe_milion": "cinci"}, MODEL, "pret_iesire"
        )

    def test_pretul_negativ(self):
        self._verifica_respins(
            {**PRETURI, "pret_intrare_usd_pe_milion": -1}, MODEL, "pret_intrare"
        )

    def test_preturile_altui_model(self):
        self._verifica_respins(PRETURI, "claude-sonnet-5-5", "claude-sonnet-5-5")

    def test_modelul_nestiut(self):
        # MODEL_NORMALIZARE lipsa din .env: nu se presupune niciun model.
        self._verifica_respins(PRETURI, None, "MODEL_NORMALIZARE")

    def test_bugetul_zero_nu_imparte_la_zero(self):
        luna = situatia_lunii("2026-09", CONSUM, {**PRETURI, "buget_lunar_usd": 0}, MODEL)

        self.assertEqual(luna["cost_usd"], 2.0)
        self.assertIsNone(luna["procent_din_buget"])


class BazaTemporara:
    """setUp/tearDown pentru o baza temporara. Nu e TestCase: nu aduce teste cu el."""

    def setUp(self):
        self.dosar = Path(tempfile.mkdtemp(prefix="agent051-test-cost-"))
        self._cale_reala = db.CALE_DB
        self._dosar_real = db.DOSAR_DATE
        db.CALE_DB = self.dosar / "test.db"
        db.DOSAR_DATE = self.dosar
        db.initializeaza_db()

    def tearDown(self):
        db.CALE_DB = self._cale_reala
        db.DOSAR_DATE = self._dosar_real
        shutil.rmtree(self.dosar, ignore_errors=True)


class TestContoareleLunare(BazaTemporara, unittest.TestCase):

    def test_consumul_se_aduna_pe_luna_si_in_totalul_istoric(self):
        db.acumuleaza_cost(2, 1000, 300, "2026-09")
        db.acumuleaza_cost(1, 500, 100, "2026-09")
        db.acumuleaza_cost(4, 7000, 900, "2026-10")

        self.assertEqual(
            db.consum_lunar("2026-09"),
            {"apeluri": 3, "tokeni_intrare": 1500, "tokeni_iesire": 400},
        )
        self.assertEqual(
            db.consum_lunar("2026-10"),
            {"apeluri": 4, "tokeni_intrare": 7000, "tokeni_iesire": 900},
        )
        self.assertEqual(
            db.cost_cumulat(), {"apeluri_total": 7, "tokeni_total": 1500 + 400 + 7900}
        )

    def test_luna_fara_rulari_da_zerouri(self):
        self.assertEqual(
            db.consum_lunar("2027-01"),
            {"apeluri": 0, "tokeni_intrare": 0, "tokeni_iesire": 0},
        )

    def test_stare_pipeline_arata_luna_curenta(self):
        from agent051.adapters.interogari import stare_pipeline

        cost = stare_pipeline()["cost"]

        self.assertIn("apeluri_total", cost)
        self.assertIn("luna_curenta", cost)
        self.assertEqual(cost["luna_curenta"]["apeluri"], 0)


class TestRulareaRuptaIsiNumaraCostul(BazaTemporara, unittest.TestCase):
    """
    O rulare care se rupe neprevazut la jumatate a platit deja apelurile facute. Pana la
    30 sept. 2026 costul se scria doar la final, deci o eroare neasteptata il pierdea.
    Apelul real e inlocuit cu unul inventat; niciun model nu e atins.
    """

    def _lot_care_cheama_o_data_si_se_rupe(self, *argumente, **_):
        cheama_model = next(a for a in argumente if callable(a))
        cheama_model("prompt")
        raise RuntimeError("baza blocata, inventat")

    def _ruleaza(self, modul, nume_lot, ruleaza):
        with mock.patch.object(modul, "verifica_infrastructura"),              mock.patch.object(modul, nume_lot, self._lot_care_cheama_o_data_si_se_rupe),              mock.patch("agent051.adapters.model._apeleaza_modelul",
                        return_value=("{}", 1000, 200)):
            with self.assertRaises(RuntimeError):
                ruleaza(dry_run=False)
        self.assertEqual(db.cost_cumulat(), {"apeluri_total": 1, "tokeni_total": 1200})

    def test_normalizarea(self):
        import agent051.adapters.normalizare as modul
        self._ruleaza(modul, "normalizeaza_lotul", modul.ruleaza_normalizarea)

    def test_evaluarea(self):
        import agent051.adapters.evaluare_calitativa as modul
        self._ruleaza(modul, "evalueaza_lotul", modul.ruleaza_evaluarea_calitativa)


if __name__ == "__main__":
    unittest.main()
