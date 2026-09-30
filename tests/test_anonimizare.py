r"""
Teste pentru core/anonimizare.py - curatarea datelor personale din ce pleaca spre afara.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

TOATE EXEMPLELE DE MAI JOS SUNT INVENTATE. Niciun subiect nu e copiat din arhiva reala,
si asta nu e o comoditate, ci chiar subiectul testului: fisierul intra in Git, iar un
test scris ca sa apere datele cuiva n-are voie sa fie el insusi locul in care datele alea
ajung publice. Numele si numerele de mai jos nu apartin nimanui.

CE VERIFICA:
1. ca ce e sigur personal (e-mail, telefon, PIN) dispare;
2. ca ce NU se poate decide sigur - un cuvant cu majuscula - se taie oricum;
3. ca ce ramane e destul cat sa recunosti un sablon de platforma;
4. ca functia nu atinge baza si nu inventeaza text.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.core.anonimizare import (
    LUNGIME_MAXIMA,
    SEMN_EMAIL,
    SEMN_NUMAR,
    SEMN_TAIAT,
    curata_subiectul,
)


class TestCeDispare(unittest.TestCase):
    """Cele trei feluri de date despre care nu incape discutie."""

    def test_adresa_de_email(self):
        curat = curata_subiectul("confirmare pentru ionel.exemplu@inventat.ro azi")

        self.assertIn(SEMN_EMAIL, curat)
        self.assertNotIn("ionel", curat)
        self.assertNotIn("@", curat)

    def test_numar_de_telefon(self):
        curat = curata_subiectul("suna la 0722 123 456 pentru detalii")

        self.assertIn(SEMN_NUMAR, curat)
        self.assertNotIn("0722", curat)
        self.assertNotIn("456", curat)

    def test_cod_pin(self):
        """Cazul din arhiva care a cerut toata schimbarea (cifrele de aici sunt inventate)."""
        curat = curata_subiectul("codul tau de acces este 4821")

        self.assertIn(SEMN_NUMAR, curat)
        self.assertNotIn("4821", curat)

    def test_sir_lung_de_cifre(self):
        curat = curata_subiectul("comanda ta 1234567890 a fost preluata")

        self.assertNotIn("1234567890", curat)

    def test_numarul_mic_ramane(self):
        """
        "34 joburi noi" - cifra aia e chiar informatia utila din subiect. Sub patru
        cifre nu se poate ascunde nici un telefon, nici un PIN.
        """
        curat = curata_subiectul("34 joburi noi pentru tine")

        self.assertIn("34", curat)
        self.assertIn("joburi", curat)


class TestCeSeTaieDinPrudenta(unittest.TestCase):
    """
    Partea care face cu adevarat treaba: numele de persoane.

    Nu exista regula care sa recunoasca un nume - "Ion" arata exact ca "Cluj". Deci se
    taie tot ce incepe cu majuscula, in afara de primul cuvant. Se pierd si nume de firme
    si de orase; e pretul, si e ales in cunostinta de cauza.
    """

    def test_numele_de_la_sfarsit_dispare(self):
        """Forma care apare cel mai des in esecurile reale: propozitie + Prenume Nume."""
        curat = curata_subiectul("felicitari pentru noul tau rol, Ionel Exemplescu")

        self.assertNotIn("Ionel", curat)
        self.assertNotIn("Exemplescu", curat)
        self.assertIn("felicitari", curat)

    def test_doua_nume_lipite_dau_UN_singur_semn(self):
        """
        Cate cuvinte avea numele cuiva e tot o informatie despre acel cineva. Si un raport
        plin de paranteze nu se mai poate citi.
        """
        curat = curata_subiectul("mesaj de la Ionel Exemplescu Popescu")

        self.assertEqual(curat.count(SEMN_TAIAT), 1)

    def test_prenumele_de_pe_PRIMA_pozitie_dispare_si_el(self):
        """
        LECTIA INVATATA PE DATE REALE, si motivul pentru care nu exista nicio exceptie.

        Prima versiune pastra primul cuvant, cu argumentul ca propozitiile incep cu
        majuscula din gramatica, nu fiindca ar fi nume. Rulata pe arhiva, a lasat la
        vedere zece subiecte care incepeau exact cu prenumele destinatarului - asa isi
        scrie LinkedIn subiectele. Exceptia scapa taman cazul cel mai frecvent.
        """
        curat = curata_subiectul("Ionel, incepeti o conversatie cu noul dvs. coleg")

        self.assertNotIn("Ionel", curat)
        self.assertIn("conversatie", curat)

    def test_pretul_renuntarii_la_exceptie_e_mic(self):
        """Perechea testului de sus: subiectul ramane la fel de recognoscibil si fara el."""
        curat = curata_subiectul("Alerta zilnica de joburi")

        self.assertNotIn("Alerta", curat)
        self.assertIn("zilnica de joburi", curat)

    def test_numele_de_firma_se_pierde_si_e_acceptat(self):
        """
        Comportament CUNOSCUT, nu scapare: un nume de firma nu se poate deosebi de unul de
        om. Sursa mesajului se vede oricum separat in raport, deci nu se pierde nimic de
        care sa depinda diagnosticul.
        """
        curat = curata_subiectul("oferta de la Firma Inventata SRL")

        self.assertNotIn("Firma", curat)
        self.assertIn("oferta", curat)

    def test_subiectul_prea_lung_se_taie(self):
        lung = "alerta " + "cuvinte marunte si nevinovate " * 20

        curat = curata_subiectul(lung)

        self.assertLessEqual(len(curat), LUNGIME_MAXIMA + 1)
        self.assertTrue(curat.endswith("…"))


class TestCeRAMANE(unittest.TestCase):
    """
    Cealalta jumatate a intelegerii: daca nu ramane nimic util, curatarea a stricat exact
    ce trebuia sa apere - posibilitatea de a recunoaste un sablon nou de platforma.
    """

    def test_sablonul_de_alerta_ramane_recognoscibil(self):
        curat = curata_subiectul("34 joburi pentru tine")

        self.assertEqual(curat, "34 joburi pentru tine")

    def test_mailul_care_nu_e_alerta_ramane_recognoscibil(self):
        """
        "Bun venit pe eJobs" - exact felul de mail din care parserul NU are ce extrage,
        si trebuie sa se vada ca nu e o problema de sablon.
        """
        curat = curata_subiectul("Bun venit pe eJobs")

        self.assertIn("venit", curat)
        self.assertIn("eJobs", curat)

    def test_cuvintele_cheie_de_diagnostic_supravietuiesc(self):
        curat = curata_subiectul("candidatura ta a fost vazuta de angajator")

        self.assertEqual(curat, "candidatura ta a fost vazuta de angajator")


class TestCazuriDeMargine(unittest.TestCase):

    def test_subiectul_gol_iese_gol(self):
        """Nu inventam un text care nu exista."""
        self.assertEqual(curata_subiectul(""), "")
        self.assertEqual(curata_subiectul("   "), "")
        self.assertEqual(curata_subiectul(None), "")

    def test_diacriticele_nu_pacalesc_regula(self):
        """"Ștefan" incepe cu majuscula la fel ca "Stefan", chiar daca litera are semn."""
        curat = curata_subiectul("mesaj pentru Ștefan Ionescu")

        self.assertNotIn("Ștefan", curat)
        self.assertNotIn("Ionescu", curat)

    def test_functia_nu_schimba_sirul_primit(self):
        """Pura inseamna si asta: primeste date, intoarce date, nu modifica nimic."""
        original = "mesaj pentru Ionel Exemplescu"

        curata_subiectul(original)

        self.assertEqual(original, "mesaj pentru Ionel Exemplescu")


class TestAplicareaInRaport(unittest.TestCase):
    """
    Regula 2 din cerinta: curatarea se aplica DOAR la iesire. Baza pastreaza subiectul
    brut, fiindca ingestia nu curata.
    """

    def test_raportul_extragerii_nu_contine_subiectul_brut(self):
        """
        Verificat pe fapte, nu pe textul codului: construim un rand de raport si ne
        uitam ce iese. Numele din subiect nu are voie sa apara nicaieri in el.

        Functia primeste subiectul BRUT si asta e in regula - ii trebuie cuvintele
        intregi ca sa afle FELUL mesajului (vezi core/esecuri.py). Important e ce
        pleaca mai departe, si acolo e doar varianta curatata.
        """
        from agent051.adapters.extragere import _mesaj_fara_anunturi

        rand = _mesaj_fara_anunturi(
            "linkedin",
            "Ionel Exemplescu, bun venit la LinkedIn",
            "niciun link de tip /jobs/view/",
        )

        self.assertNotIn("Ionel", str(rand))
        self.assertNotIn("Exemplescu", str(rand))
        # Ce ramane e destul cat sa recunosti sablonul.
        self.assertIn("venit la", rand["subiect"])

    def test_extragerea_cheama_curatarea_pe_subiect(self):
        import inspect

        from agent051.adapters import extragere

        sursa = inspect.getsource(extragere)

        self.assertIn("curata_subiectul(subiect_brut)", sursa)
        # Subiectul brut nu mai ajunge in raport pe nicio cale.
        self.assertNotIn('"subiect": mesaj["subiect"]', sursa)
        self.assertNotIn('"subiect": subiect_brut', sursa)

    def test_ingestia_NU_curata_nimic_inainte_de_salvare(self):
        """
        Plasa in cealalta directie: daca cineva ar aplica curatarea la ingestie, subiectele
        s-ar pierde definitiv din baza si n-ar mai putea fi recuperate niciodata.
        """
        import inspect

        from agent051.adapters import ingestie

        self.assertNotIn("curata_subiectul", inspect.getsource(ingestie))


if __name__ == "__main__":
    unittest.main()
