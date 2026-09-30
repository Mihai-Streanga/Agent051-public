r"""
Teste pentru salariul luat din datele structurate ale paginii (datoria 7, 29 sept. 2026).

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

Functia din core/ se testeaza pe o pagina eJobs REALA din tests/pagini/ si pe bucati
mici de JSON-LD, scrise aici ca sa se vada exact ce camp produce ce. Fara retea, fara baza.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.adapters import filtrare as adaptor_filtrare
from agent051.core.descriere import salariul_din_pagina, tarile_din_pagina
from agent051.core.filtrare import filtreaza_dur

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_filtrare import CRITERII as CRITERII_DE_BAZA  # noqa: E402

PAGINI = Path(__file__).resolve().parent / "pagini"


def pagina_cu(base_salary) -> str:
    """O pagina minima, cu un singur nod JobPosting care are baseSalary-ul dat."""
    nod = {"@type": "JobPosting", "title": "Rol", "description": "<p>text</p>"}
    if base_salary is not None:
        nod["baseSalary"] = base_salary
    return (
        '<html><script type="application/ld+json">'
        + json.dumps({"@graph": [nod]})
        + "</script></html>"
    )


def interval(minim, maxim, moneda="RON", **in_plus) -> dict:
    valoare = {"@type": "QuantitativeValue", "minValue": minim, "maxValue": maxim}
    valoare.update(in_plus)
    return {"@type": "MonetaryAmount", "currency": moneda, "value": valoare}


class TestSalariulDinPagina(unittest.TestCase):

    def test_pagina_reala_ejobs(self):
        html = (PAGINI / "ejobs_customer_support.html").read_text(encoding="utf-8")
        self.assertEqual(salariul_din_pagina(html, "ejobs"), "4000 - 5000 RON (din pagina)")

    def test_valuta_straina_ramane_scrisa(self):
        # Filtrul o vede si o raporteaza "necomparabil" - nu ghicim cursul.
        self.assertEqual(
            salariul_din_pagina(pagina_cu(interval("1500", "3000", "EUR")), "ejobs"),
            "1500 - 3000 EUR (din pagina)",
        )

    def test_fara_base_salary_e_sir_gol(self):
        self.assertEqual(salariul_din_pagina(pagina_cu(None), "ejobs"), "")

    def test_alta_unitate_decat_luna_e_sir_gol(self):
        pagina = pagina_cu(interval("60000", "90000", unitText="YEAR"))
        self.assertEqual(salariul_din_pagina(pagina, "ejobs"), "")

    def test_luna_scrisa_explicit_e_acceptata(self):
        pagina = pagina_cu(interval("8000", "9000", unitText="MONTH"))
        self.assertEqual(salariul_din_pagina(pagina, "ejobs"), "8000 - 9000 RON (din pagina)")

    def test_cifre_care_nu_sunt_numere_sunt_respinse(self):
        pagina = pagina_cu(interval("negociabil", "", "RON"))
        self.assertEqual(salariul_din_pagina(pagina, "ejobs"), "")

    def test_numere_cu_zecimala_zero_sunt_acceptate(self):
        # JSON-ul poate scrie 4000.0 in loc de 4000; e aceeasi suma.
        pagina = pagina_cu(interval(4000.0, "5000.0"))
        self.assertEqual(salariul_din_pagina(pagina, "ejobs"), "4000 - 5000 RON (din pagina)")

    def test_zecimale_adevarate_sunt_respinse(self):
        pagina = pagina_cu(interval("4000.5", "4000.5"))
        self.assertEqual(salariul_din_pagina(pagina, "ejobs"), "")

    def test_interval_si_valoare_nu_se_lipesc(self):
        # Forma reala de pe 2 pagini eJobs, 30 sept. 2026.
        pagina = pagina_cu(interval("3500", "3500", value="3500"))
        self.assertEqual(salariul_din_pagina(pagina, "ejobs"), "3500 RON (din pagina)")

    def test_doar_valoare_unica(self):
        pagina = pagina_cu(
            {"@type": "MonetaryAmount", "currency": "RON", "value": {"value": 6000}}
        )
        self.assertEqual(salariul_din_pagina(pagina, "ejobs"), "6000 RON (din pagina)")

    def test_bestjobs_nu_da_salariu(self):
        # estimatedSalary de la BestJobs e o estimare a platformei, nu oferta firmei.
        pagina = (PAGINI / "bestjobs_multilingual_hrbp.html").read_text(encoding="utf-8")
        self.assertEqual(salariul_din_pagina(pagina, "bestjobs"), "")

    def test_pagina_goala_e_sir_gol(self):
        self.assertEqual(salariul_din_pagina("", "ejobs"), "")


class TestFiltrulCitesteSalariulDinPagina(unittest.TestCase):
    """Textul produs trebuie sa fie inteles de filtru exact ca un salariu din mail."""

    CRITERII = {
        "constrangeri_dure": {
            "venit_net_lunar_ron": {"prag_respingere": 5000},
            "locatie": {"baza": "Brașov", "remote_acceptat": True},
            "rol_structura": {"cuvinte_excluse": ["ture"]},
            "limbi": CRITERII_DE_BAZA["constrangeri_dure"]["limbi"],
        }
    }

    def filtreaza(self, salariu: str) -> dict:
        anunt = {"titlu": "Specialist Payroll", "locatie": "Brașov",
                 "tip_munca": "remote", "salariu_brut": salariu}
        return filtreaza_dur(anunt, self.CRITERII)

    def test_sub_prag_din_pagina_e_respins(self):
        rezultat = self.filtreaza("3000 - 4000 RON (din pagina)")
        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("(din pagina)", rezultat["motive_respingere"][0])

    def test_euro_din_pagina_e_necomparabil_nu_respins(self):
        rezultat = self.filtreaza("1500 - 3000 EUR (din pagina)")
        self.assertEqual(rezultat["motive_respingere"], [])


class TestAdaptorulIaPaginaDoarCandTrebuie(unittest.TestCase):
    """Salariul din mail castiga; pagina se citeste doar la anunturile cu pagina salvata."""

    def setUp(self):
        self.cerute = []
        self._pagina_reala = adaptor_filtrare.pagina_salvata
        html = (PAGINI / "ejobs_customer_support.html").read_text(encoding="utf-8")

        def pagina_de_test(anunt_id):
            self.cerute.append(anunt_id)
            return html

        adaptor_filtrare.pagina_salvata = pagina_de_test

    def tearDown(self):
        adaptor_filtrare.pagina_salvata = self._pagina_reala

    def completeaza(self, **campuri):
        anunt = {"id": "A", "sursa": "ejobs", "status_pagina": "ok", "salariu_brut": ""}
        anunt.update(campuri)
        return adaptor_filtrare._cu_datele_din_pagina(anunt)

    def test_mail_fara_salariu_primeste_salariul_si_tara_din_pagina(self):
        rezultat = self.completeaza()
        self.assertEqual(rezultat["salariu_brut"], "4000 - 5000 RON (din pagina)")
        self.assertEqual(rezultat["tari_din_pagina"], ["RO"])

    def test_salariul_din_mail_ramane(self):
        rezultat = self.completeaza(salariu_brut="9000 RON")
        self.assertEqual(rezultat["salariu_brut"], "9000 RON")
        self.assertEqual(self.cerute, ["A"])  # pagina tot se citeste, pentru tara

    def test_originalul_nu_se_modifica(self):
        anunt = {"id": "A", "sursa": "ejobs", "status_pagina": "ok", "salariu_brut": ""}
        adaptor_filtrare._cu_datele_din_pagina(anunt)
        self.assertNotIn("tari_din_pagina", anunt)

    def test_fara_pagina_salvata_nu_se_citeste_nimic(self):
        for campuri in ({"status_pagina": None}, {"sursa": "linkedin"}):
            self.assertNotIn("tari_din_pagina", self.completeaza(**campuri))
        self.assertEqual(self.cerute, [])


class TestTaraDinPagina(unittest.TestCase):

    def test_pagina_reala_ejobs_e_in_romania(self):
        html = (PAGINI / "ejobs_customer_support.html").read_text(encoding="utf-8")
        self.assertEqual(tarile_din_pagina(html, "ejobs"), ["RO"])

    def test_rezidenta_ceruta_la_remote(self):
        pagina = pagina_cu(None).replace(
            '"@type": "JobPosting"',
            '"@type": "JobPosting", "applicantLocationRequirements": '
            '{"@type": "Country", "name": "Germany"}',
        )
        self.assertEqual(tarile_din_pagina(pagina, "ejobs"), ["Germany"])

    def test_romania_scrisa_in_orice_fel_devine_RO(self):
        pagina = pagina_cu(None).replace(
            '"@type": "JobPosting"',
            '"@type": "JobPosting", "jobLocation": [{"address": {"addressCountry": "Romania"}}],'
            ' "applicantLocationRequirements": {"name": "România"}',
        )
        self.assertEqual(tarile_din_pagina(pagina, "ejobs"), ["RO"])

    def test_remote_din_romania_la_firma_straina_ramane_RO(self):
        # Sediul in Germania, dar candidatul trebuie sa fie in Romania: rezidenta decide.
        # Pana la 30 sept. 2026 iesea ["DE", "RO"], iar filtrul respingea pe "DE".
        pagina = pagina_cu(None).replace(
            '"@type": "JobPosting"',
            '"@type": "JobPosting", "jobLocation": [{"address": {"addressCountry": "DE"}}],'
            ' "applicantLocationRequirements": {"@type": "Country", "name": "Romania"}',
        )
        self.assertEqual(tarile_din_pagina(pagina, "ejobs"), ["RO"])

    def test_fara_rezidenta_decide_adresa(self):
        pagina = pagina_cu(None).replace(
            '"@type": "JobPosting"',
            '"@type": "JobPosting", "jobLocation": [{"address": {"addressCountry": "DE"}}]',
        )
        self.assertEqual(tarile_din_pagina(pagina, "ejobs"), ["DE"])

    def test_tara_scrisa_ca_obiect_schema_org(self):
        pagina = pagina_cu(None).replace(
            '"@type": "JobPosting"',
            '"@type": "JobPosting", "jobLocation": [{"address": '
            '{"addressCountry": {"@type": "Country", "name": "RO"}}}]',
        )
        self.assertEqual(tarile_din_pagina(pagina, "ejobs"), ["RO"])

    def test_bestjobs_real_nu_e_in_strainatate(self):
        pagina = (PAGINI / "bestjobs_multilingual_hrbp.html").read_text(encoding="utf-8")
        self.assertEqual(tarile_din_pagina(pagina, "bestjobs"), [])

    def test_pagina_fara_date_nu_spune_nimic(self):
        self.assertEqual(tarile_din_pagina("", "ejobs"), [])


class TestFiltrulPeTara(unittest.TestCase):

    CRITERII = {
        "constrangeri_dure": {
            "venit_net_lunar_ron": {"prag_respingere": 5000},
            "locatie": {"baza": "Brașov", "remote_acceptat": True,
                        "tara_firma": {"permis": ["RO"]}},
            "rol_structura": {"cuvinte_excluse": ["ture"]},
            "limbi": CRITERII_DE_BAZA["constrangeri_dure"]["limbi"],
        }
    }

    def filtreaza(self, tari, criterii=None) -> dict:
        anunt = {"titlu": "Specialist Payroll", "locatie": "Brașov", "tip_munca": "remote",
                 "salariu_brut": "9000 RON", "tari_din_pagina": tari}
        return filtreaza_dur(anunt, criterii or self.CRITERII)

    def test_romania_trece(self):
        self.assertEqual(self.filtreaza(["RO"])["verdict"], "trece")

    def test_alta_tara_e_respinsa_cu_tara_la_vedere(self):
        rezultat = self.filtreaza(["Germany"])
        self.assertEqual(rezultat["verdict"], "respins")
        self.assertEqual(rezultat["motive_respingere"], ["tara in afara zonei: Germany (din pagina)"])

    def test_strainatate_bestjobs_e_respinsa(self):
        self.assertEqual(self.filtreaza(["strainatate"])["verdict"], "respins")

    def test_tara_necunoscuta_nu_respinge_si_nu_se_raporteaza(self):
        rezultat = self.filtreaza([])
        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["necunoscute"], [])

    def test_tara_permisa_lipsa_din_criterii_blocheaza(self):
        criterii = {"constrangeri_dure": {**self.CRITERII["constrangeri_dure"],
                    "locatie": {"baza": "Brașov", "remote_acceptat": True}}}
        rezultat = self.filtreaza(["RO"], criterii)
        self.assertEqual(rezultat["verdict"], "incert")
        self.assertIn("tara permisa lipsa din criterii.yaml", rezultat["necunoscute"])

if __name__ == "__main__":
    unittest.main()
