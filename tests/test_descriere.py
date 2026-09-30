r"""
Teste pentru completarea descrierilor - extragerea (core) si orchestrarea (adapter).

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

UITA-TE CE NU E AICI.
Nicio cerere de retea. Niciun site atins. Nicio baza de date. Paginile sunt fisiere pe
disc, in tests/pagini/, taiate din pagini REALE de eJobs si BestJobs - blocul de date
structurate e neatins, cu descrierea exact cum a venit de la server. Iar cititorul de
pagini se INJECTEAZA ca functie (adresa) -> dict: mai jos e o galerie de cititori
inventati, unul care raspunde bine si mai multi care esueaza in feluri diferite.

DE CE fixture-uri reale si nu HTML scris de mana: un parser verificat pe HTML inventat
de noi verifica doar ca intelegem ce-am scris tot noi. Structura reala are surprize -
la eJobs, descrierea sta intr-un @graph cu zece noduri, dintre care unul singur e
JobPosting; la BestJobs, intr-o incarcatura Next.js de 636 KB.

CE VERIFICA, DE FAPT:
1. ca descrierea chiar se scoate din pagini reale, la ambele surse;
2. ca o structura nerecunoscuta iese ca ESEC MOTIVAT, niciodata ca text gol;
3. ca un esec de RETEA opreste rularea, in loc sa marcheze anunturi "fara descriere";
4. ca un anunt expirat (404) e un FAPT salvat, nu o eroare care opreste;
5. ca plasele (sursa, link, descriere existenta, pagina luata, varsta, limita, dry run)
   taie exact pe cine trebuie;
6. ca un 200 primit pe ALTA pagina (eJobs redirecteaza anunturile moarte catre lista
   generala) iese `expirat`, nu `fara_descriere` - vezi pagina_e_a_anuntului.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.adapters.descrieri import (
    STATUS_FARA_DESCRIERE,
    alege_anunturile,
    ia_descrierea_unui_anunt,
    ia_lotul,
)
from agent051.core.descriere import (
    extrage_descrierea,
    extrage_din_bestjobs,
    extrage_din_ejobs,
    extrage_firma_si_titlul,
    pagina_e_a_anuntului,
    titlul_de_pastrat,
)
from agent051.ingest.pagini import (
    STATUS_EXPIRAT,
    STATUS_INTERZIS_ROBOTS,
    STATUS_OK,
    EroareRetea,
)

DOSAR_PAGINI = Path(__file__).resolve().parent / "pagini"

ACUM = datetime(2026, 7, 26, tzinfo=timezone.utc)
IERI = (ACUM - timedelta(days=1)).isoformat()
ACUM_DOI_ANI = (ACUM - timedelta(days=730)).isoformat()
SURSE = ("ejobs", "bestjobs")


def pagina(nume: str) -> str:
    """O pagina salvata pe disc. Fara retea, fara surprize."""
    return (DOSAR_PAGINI / nume).read_text(encoding="utf-8")


def anunt(
    id_anunt: str = "a1",
    sursa: str = "ejobs",
    link: str = "https://www.ejobs.ro/user/locuri-de-munca/ceva/1",
    descriere: str = None,
    data_anunt: str = IERI,
    status_pagina: str = None,
) -> dict:
    """Un anunt inventat, cu valori implicite care il fac ELIGIBIL."""
    return {
        "id": id_anunt,
        "sursa": sursa,
        "titlu": f"Rol inventat {id_anunt}",
        "link": link,
        "descriere": descriere,
        "data_anunt": data_anunt,
        "status_pagina": status_pagina,
    }


# ---------------------------------------------------------------------------
# Galeria de cititori de pagini inventati. Fiecare e (adresa) -> dict.
# ---------------------------------------------------------------------------

def cititor_ejobs_bun(adresa: str) -> dict:
    return {"status": STATUS_OK, "html": pagina("ejobs_senior_hr_business_partner.html"),
            "cod_http": 200, "motiv": ""}


def cititor_pagina_expirata(adresa: str) -> dict:
    return {"status": STATUS_EXPIRAT, "html": None, "cod_http": 404,
            "motiv": "pagina nu mai exista (404)"}


def cititor_interzis_de_robots(adresa: str) -> dict:
    return {"status": STATUS_INTERZIS_ROBOTS, "html": None, "cod_http": None,
            "motiv": "robots.txt nu permite adresa asta"}


def cititor_pagina_straina(adresa: str) -> dict:
    """A raspuns 200, dar cu o pagina din care nu se poate scoate nicio descriere."""
    return {"status": STATUS_OK, "html": "<html><body><h1>Ceva</h1></body></html>",
            "cod_http": 200, "motiv": ""}


def cititor_blocat(adresa: str) -> dict:
    """Sursa ne-a blocat (403). NU e un fapt despre anunt."""
    raise EroareRetea("https://exemplu.invalid a raspuns cu 403 - nu s-a ajuns la pagina")


def cititor_trimis_la_lista(adresa: str) -> dict:
    """
    Ce face eJobs cu un anunt care nu mai exista: 302 catre lista generala de joburi.
    Cod 200, pagina intreaga si valida - doar ca a altcuiva.

    HTML-ul e scurt dinadins, desi restul fixture-urilor sunt pagini reale: pagina reala
    de lista are 960 KB si nici nu se citeste vreodata aici. Decizia se ia pe adrese,
    inainte sa se atinga HTML-ul - si exact asta verifica testul.
    """
    return {"status": STATUS_OK, "html": "<html><body>13606 joburi</body></html>",
            "cod_http": 200, "motiv": "",
            "adresa_finala": "https://www.ejobs.ro/locuri-de-munca"}


def cititor_redirectat_la_forma_lunga(adresa: str) -> dict:
    """
    Redirectul LEGITIM al eJobs: forma scurta `/j/<id>` duce la cea cu nume in adresa.
    Tot pagina anuntului, deci trebuie sa treaca. Aici se vede de ce regula nu compara
    adresele cap-coada, ci se uita daca identificatorul a supravietuit.
    """
    return {"status": STATUS_OK, "html": pagina("ejobs_senior_hr_business_partner.html"),
            "cod_http": 200, "motiv": "",
            "adresa_finala": "https://www.ejobs.ro/user/locuri-de-munca/senior-hr/1973309"}


# ===========================================================================
# CORE: extragerea, pe pagini reale salvate pe disc
# ===========================================================================

class TestExtragereEjobs(unittest.TestCase):

    def test_scoate_descrierea_dintr_o_pagina_reala(self):
        """Pagina reala eJobs: descrierea sta in ld+json, la nodul JobPosting."""
        rezultat = extrage_din_ejobs(pagina("ejobs_senior_hr_business_partner.html"))

        self.assertTrue(rezultat["ok"], rezultat.get("motiv"))
        text = rezultat["descriere"]
        self.assertIn("Senior Business Partner HR Development", text)
        self.assertIn("talent development", text)
        # Textul e curatat de HTML: etichetele au disparut, randurile au ramas.
        self.assertNotIn("<br", text)
        self.assertNotIn("</p>", text)
        self.assertGreater(len(text.splitlines()), 5)

    def test_merge_si_pe_a_doua_pagina_reala(self):
        """Alta pagina, alt sablon de URL, text in romana cu diacritice."""
        rezultat = extrage_din_ejobs(pagina("ejobs_customer_support.html"))

        self.assertTrue(rezultat["ok"], rezultat.get("motiv"))
        self.assertIn("Customer Support", rezultat["descriere"])
        # Diacriticele supravietuiesc drumului prin JSON si prin curatarea de HTML.
        self.assertIn("ă", rezultat["descriere"])

    def test_pagina_fara_ld_json_e_esec_motivat(self):
        """Fara bloc ld+json: esec cu motiv, NU descriere goala."""
        rezultat = extrage_din_ejobs("<html><body><p>Salut</p></body></html>")

        self.assertFalse(rezultat["ok"])
        self.assertIn("ld+json", rezultat["motiv"])
        self.assertNotIn("descriere", rezultat)

    def test_ld_json_fara_jobposting_e_esec_motivat(self):
        """Blocul exista, dar nu are nodul care ne trebuie. Motivul spune exact asta."""
        html = ('<script type="application/ld+json">'
                '{"@context":"https://schema.org","@graph":[{"@type":"WebSite"}]}</script>')
        rezultat = extrage_din_ejobs(html)

        self.assertFalse(rezultat["ok"])
        self.assertIn("JobPosting", rezultat["motiv"])

    def test_jobposting_fara_description_e_esec_motivat(self):
        html = ('<script type="application/ld+json">'
                '{"@type":"JobPosting","title":"Ceva"}</script>')
        rezultat = extrage_din_ejobs(html)

        self.assertFalse(rezultat["ok"])
        self.assertIn("description", rezultat["motiv"])

    def test_ld_json_stricat_e_esec_nu_exceptie(self):
        """Un JSON cu o virgula lipsa iese ca respingere, nu darama rularea."""
        html = '<script type="application/ld+json">{"@type": "JobPosting" ,,}</script>'
        rezultat = extrage_din_ejobs(html)

        self.assertFalse(rezultat["ok"])
        self.assertIn("JSON valid", rezultat["motiv"])

    def test_jobposting_gasit_si_cand_nu_e_primul_bloc(self):
        """Doua blocuri ld+json: il gaseste pe cel bun, nu se opreste la primul."""
        html = (
            '<script type="application/ld+json">{"@type":"Organization"}</script>'
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","description":"<p>Automatizezi procese.</p>"}</script>'
        )
        rezultat = extrage_din_ejobs(html)

        self.assertTrue(rezultat["ok"])
        self.assertEqual(rezultat["descriere"], "Automatizezi procese.")


class TestExtragereBestjobs(unittest.TestCase):

    def test_scoate_descrierea_dintr_o_pagina_reala(self):
        """Pagina reala BestJobs: descrierea sta in __NEXT_DATA__."""
        rezultat = extrage_din_bestjobs(pagina("bestjobs_multilingual_hrbp.html"))

        self.assertTrue(rezultat["ok"], rezultat.get("motiv"))
        text = rezultat["descriere"]
        self.assertIn("Human Resources Business Partner", text)
        self.assertIn("Key Responsibilities", text)
        self.assertNotIn("<span>", text)
        self.assertNotIn("<li>", text)

    def test_pagina_fara_next_data_e_esec_motivat(self):
        rezultat = extrage_din_bestjobs("<html><body>nimic</body></html>")

        self.assertFalse(rezultat["ok"])
        self.assertIn("__NEXT_DATA__", rezultat["motiv"])

    def test_calea_rupta_spune_UNDE_s_a_rupt(self):
        """
        Un motiv trebuie sa fie reparabil. "n-a mers" nu e; "rupt la 'job'" e.

        Daca BestJobs isi rearanjeaza incarcatura, mesajul asta iti spune direct la ce
        cheie sa te uiti, fara sa mai descarci pagina o data.
        """
        html = ('<script id="__NEXT_DATA__" type="application/json">'
                '{"props":{"pageProps":{}}}</script>')
        rezultat = extrage_din_bestjobs(html)

        self.assertFalse(rezultat["ok"])
        self.assertIn("job", rezultat["motiv"])


class TestExtragereDupaSursa(unittest.TestCase):

    def test_alege_parserul_dupa_sursa(self):
        for sursa, fisier, asteptat in (
            ("ejobs", "ejobs_senior_hr_business_partner.html", "Senior Business Partner"),
            ("bestjobs", "bestjobs_multilingual_hrbp.html", "Human Resources Business Partner"),
        ):
            with self.subTest(sursa=sursa):
                rezultat = extrage_descrierea(pagina(fisier), sursa)
                self.assertTrue(rezultat["ok"], rezultat.get("motiv"))
                self.assertIn(asteptat, rezultat["descriere"])

    def test_sursa_necunoscuta_e_esec_motivat(self):
        """LinkedIn n-are parser de pagina. Se spune, nu se intoarce text gol."""
        rezultat = extrage_descrierea("<html></html>", "linkedin")

        self.assertFalse(rezultat["ok"])
        self.assertIn("linkedin", rezultat["motiv"])

    def test_pagina_goala_e_esec_motivat(self):
        for gol in ("", "   ", None):
            with self.subTest(html=repr(gol)):
                rezultat = extrage_descrierea(gol, "ejobs")
                self.assertFalse(rezultat["ok"])

    def test_descrierea_goala_dupa_curatare_e_esec_nu_text_gol(self):
        """
        Miezul regulii: un sir gol salvat in baza arata identic cu "anuntul n-are
        descriere". Atunci n-ai cum sa stii daca e de reparat parserul. Deci: esec.
        """
        html = ('<script type="application/ld+json">'
                '{"@type":"JobPosting","description":"<p>  </p><br/>"}</script>')
        rezultat = extrage_descrierea(html, "ejobs")

        self.assertFalse(rezultat["ok"])
        self.assertIn("goala", rezultat["motiv"])


# ===========================================================================
# ADAPTER: un anunt, alegerea lotului, lotul intreg
# ===========================================================================

class TestUnAnunt(unittest.TestCase):

    def test_pagina_buna_da_descriere_si_html_brut(self):
        """Se salveaza AMANDOUA: textul extras si pagina bruta din care a iesit."""
        rezultat = ia_descrierea_unui_anunt(anunt(), cititor_ejobs_bun)

        self.assertEqual(rezultat["status"], STATUS_OK)
        self.assertIn("Senior Business Partner", rezultat["descriere"])
        self.assertIn("<!doctype html>", rezultat["html"])

    def test_anuntul_expirat_e_un_fapt_salvat(self):
        """404 = anuntul nu mai exista. Se salveaza si se merge mai departe."""
        rezultat = ia_descrierea_unui_anunt(anunt(), cititor_pagina_expirata)

        self.assertEqual(rezultat["status"], STATUS_EXPIRAT)
        self.assertIsNone(rezultat["html"])
        self.assertIsNone(rezultat["descriere"])

    def test_interzis_de_robots_e_tot_un_fapt_salvat(self):
        rezultat = ia_descrierea_unui_anunt(anunt(), cititor_interzis_de_robots)

        self.assertEqual(rezultat["status"], STATUS_INTERZIS_ROBOTS)
        self.assertIsNone(rezultat["html"])

    def test_pagina_nerecunoscuta_pastreaza_HTML_ul_pentru_reparatie(self):
        """
        Parserul n-a gasit textul, dar HTML-ul se salveaza oricum.

        Ala e chiar cazul in care ai nevoie de el: repari parserul si re-extragi din
        baza, fara sa mai ceri pagina si fara sa depinzi de faptul ca anuntul mai exista.
        """
        rezultat = ia_descrierea_unui_anunt(anunt(), cititor_pagina_straina)

        self.assertEqual(rezultat["status"], STATUS_FARA_DESCRIERE)
        self.assertIsNotNone(rezultat["html"])
        self.assertIsNone(rezultat["descriere"])
        self.assertIn("ld+json", rezultat["motiv"])

    def test_esecul_de_retea_PROPAGA_nu_se_preface_in_fara_descriere(self):
        """O sursa care ne blocheaza nu are voie sa marcheze anunturi 'fara descriere'."""
        with self.assertRaises(EroareRetea):
            ia_descrierea_unui_anunt(anunt(), cititor_blocat)

    def test_trimis_la_lista_e_ANUNT_EXPIRAT_nu_parser_stricat(self):
        """
        Datoria din 17 august 2026, si e chiar cazul care a produs-o.

        eJobs raspunde la un anunt mort cu 302 catre lista generala: cod 200 si o pagina
        valida. Inainte ieseau `fara_descriere`, adica "repara parserul" - o datorie
        inventata, care nu putea fi inchisa niciodata. Faptul adevarat e ca anuntul nu
        mai e, si asta se numeste `expirat`.
        """
        rezultat = ia_descrierea_unui_anunt(
            anunt(link="https://www.ejobs.ro/user/locuri-de-munca/j/1976203"),
            cititor_trimis_la_lista,
        )

        self.assertEqual(rezultat["status"], STATUS_EXPIRAT)
        self.assertNotEqual(rezultat["status"], STATUS_FARA_DESCRIERE)
        self.assertIsNone(rezultat["descriere"])
        # Pagina altcuiva NU se salveaza: pastrata in `pagina_html`, ar face ca fiecare
        # re-extragere de mai tarziu sa citeasca lista de joburi crezand ca e anuntul.
        self.assertIsNone(rezultat["html"])
        self.assertIn("ejobs.ro/locuri-de-munca", rezultat["motiv"])

    def test_redirectul_legitim_nu_strica_nimic(self):
        """Forma scurta `/j/<id>` duce la cea cu nume in adresa. Tot anuntul cerut."""
        rezultat = ia_descrierea_unui_anunt(
            anunt(link="https://www.ejobs.ro/user/locuri-de-munca/j/1973309"),
            cititor_redirectat_la_forma_lunga,
        )

        self.assertEqual(rezultat["status"], STATUS_OK)
        self.assertIn("Senior Business Partner", rezultat["descriere"])

    def test_cititorul_fara_adresa_finala_e_crezut_pe_cuvant(self):
        """
        Un cititor care nu spune unde a ajuns nu declanseaza nicio banuiala.

        Lipsa informatiei nu e o dovada: un "expirat" scos din ea ar marca anunturi vii
        ca moarte. `cititor_ejobs_bun` e chiar asa - nu intoarce `adresa_finala`.
        """
        rezultat = ia_descrierea_unui_anunt(anunt(), cititor_ejobs_bun)

        self.assertEqual(rezultat["status"], STATUS_OK)


class TestPaginaEAAnuntului(unittest.TestCase):
    """
    Regula pura: pagina la care am ajuns e a anuntului cerut? Doua siruri, un raspuns.
    Adresele sunt cele reale, masurate pe 17 august 2026.
    """

    def test_redirectul_catre_lista_generala_se_vede(self):
        self.assertFalse(pagina_e_a_anuntului(
            "https://www.ejobs.ro/user/locuri-de-munca/j/1976203",
            "https://www.ejobs.ro/locuri-de-munca",
        ))

    def test_redirectul_de_la_forma_scurta_la_cea_lunga_trece(self):
        """Identificatorul supravietuieste, deci e tot pagina anuntului."""
        self.assertTrue(pagina_e_a_anuntului(
            "https://www.ejobs.ro/user/locuri-de-munca/j/1974474",
            "https://www.ejobs.ro/user/locuri-de-munca/customer-support/1974474",
        ))

    def test_adresa_neschimbata_trece(self):
        """BestJobs nu redirecteaza deloc: adresa finala e cea ceruta."""
        adresa = "https://www.bestjobs.eu/loc-de-munca/hr-generalist-with-czech"
        self.assertTrue(pagina_e_a_anuntului(adresa, adresa))

    def test_anuntul_cu_nume_in_adresa_trimis_la_lista_se_vede(self):
        """Al doilea dintre cele trei reale: are nume in adresa, si tot a fost mutat."""
        self.assertFalse(pagina_e_a_anuntului(
            "https://www.ejobs.ro/user/locuri-de-munca/customer-support-specialist"
            "-with-foreign-language/1976414",
            "https://www.ejobs.ro/locuri-de-munca",
        ))

    def test_parametrii_si_ancora_nu_conteaza(self):
        """`?utm=...` si `#aplica` n-au nicio legatura cu ce pagina e."""
        self.assertTrue(pagina_e_a_anuntului(
            "https://www.ejobs.ro/user/locuri-de-munca/ceva/12345?utm_source=mail",
            "https://www.ejobs.ro/user/locuri-de-munca/ceva/12345#aplica",
        ))

    def test_adresa_finala_goala_nu_e_o_dovada(self):
        """Fara informatie despre unde am ajuns, nu inventam o expirare."""
        adresa = "https://www.ejobs.ro/user/locuri-de-munca/ceva/1"
        self.assertTrue(pagina_e_a_anuntului(adresa, ""))
        self.assertTrue(pagina_e_a_anuntului(adresa, None))

    def test_bara_de_la_final_nu_schimba_raspunsul(self):
        self.assertTrue(pagina_e_a_anuntului(
            "https://www.ejobs.ro/user/locuri-de-munca/ceva/12345",
            "https://www.ejobs.ro/user/locuri-de-munca/ceva/12345/",
        ))


class TestAlegereaAnunturilor(unittest.TestCase):

    def test_taie_pe_fiecare_motiv_in_parte(self):
        anunturi = [
            anunt("bun"),
            anunt("linkedin", sursa="linkedin"),
            anunt("fara_link", link=""),
            anunt("are_text", descriere="Deja stim ce scrie in el."),
            anunt("luata", status_pagina=STATUS_OK),
            anunt("mort", status_pagina=STATUS_EXPIRAT),
            anunt("vechi", data_anunt=ACUM_DOI_ANI),
        ]

        ales = alege_anunturile(anunturi, SURSE, ACUM, zile=30)

        self.assertEqual([a["id"] for a in ales["eligibile"]], ["bun"])
        self.assertEqual(ales["sarite"]["sursa_fara_parser"], 1)
        self.assertEqual(ales["sarite"]["fara_link"], 1)
        self.assertEqual(ales["sarite"]["au_deja_descriere"], 1)
        self.assertEqual(ales["sarite"]["pagina_deja_luata"], 1)
        self.assertEqual(ales["sarite"]["anunt_expirat"], 1)
        self.assertEqual(ales["sarite"]["prea_vechi"], 1)

    def test_pagina_luata_si_anunt_expirat_se_numara_SEPARAT(self):
        """
        Amandoua opresc cererea, dar spun lucruri diferite: "avem textul" si "nu-l vom
        avea niciodata". Adunate, n-ai cum sa vezi cate anunturi au murit.
        """
        anunturi = [
            anunt("luata", status_pagina=STATUS_OK),
            anunt("mort1", status_pagina=STATUS_EXPIRAT),
            anunt("mort2", status_pagina=STATUS_EXPIRAT),
        ]

        sarite = alege_anunturile(anunturi, SURSE, ACUM, 30)["sarite"]

        self.assertEqual(sarite["pagina_deja_luata"], 1)
        self.assertEqual(sarite["anunt_expirat"], 2)

    def test_anuntul_expirat_nu_se_mai_cere_niciodata(self):
        """
        Pana pe 17 august 2026 se recerea la fiecare rulare, cu argumentul ca o cerere nu
        costa bani. Costa altceva: trei pagini moarte cerute mereu, si un avertisment
        permanent in briefing pe care nicio rulare nu-l putea stinge.

        Un anunt repostat e un anunt NOU, cu alt link, care vine intr-un mail nou - nu
        acelasi rand inviat.
        """
        ales = alege_anunturile(
            [anunt("mort", status_pagina=STATUS_EXPIRAT)], SURSE, ACUM, 30
        )

        self.assertEqual(ales["eligibile"], [])
        self.assertEqual(ales["sarite"]["anunt_expirat"], 1)

    def test_interzis_de_robots_se_reincearca(self):
        """robots.txt se poate schimba, iar reincercarea nu cere nicio pagina."""
        ales = alege_anunturile(
            [anunt("robots", status_pagina=STATUS_INTERZIS_ROBOTS)], SURSE, ACUM, 30
        )

        self.assertEqual([a["id"] for a in ales["eligibile"]], ["robots"])

    def test_anuntul_fara_data_nu_e_considerat_recent(self):
        """Cand nu stim varsta, nu ghicim in favoarea noastra. Vezi normalizare."""
        ales = alege_anunturile([anunt("fara_data", data_anunt=None)], SURSE, ACUM, 30)

        self.assertEqual(ales["eligibile"], [])
        self.assertEqual(ales["sarite"]["prea_vechi"], 1)

    def test_o_pagina_esuata_se_reincearca(self):
        """
        Doar 'ok' opreste o noua incercare. Un 'fara_descriere' de ieri trebuie sa mai
        aiba o sansa dupa ce se repara parserul - altfel reparatia n-ar ajunge nicaieri.
        """
        anunturi = [anunt("de_reincercat", status_pagina=STATUS_FARA_DESCRIERE)]

        ales = alege_anunturile(anunturi, SURSE, ACUM, 30)

        self.assertEqual([a["id"] for a in ales["eligibile"]], ["de_reincercat"])


class TestLotul(unittest.TestCase):

    def _salveaza_noteaza(self, jurnal):
        """Un `salveaza` fals, care doar tine minte ce s-a scris. Fara disc."""
        def salveaza(anunt_id, rezultat):
            jurnal.append((anunt_id, rezultat))
        return salveaza

    def test_dry_run_NU_cere_nicio_pagina(self):
        """Cititor care explodeaza daca e atins: daca dry run-ul cere ceva, testul pica."""
        def cititor_care_explodeaza(adresa):
            raise AssertionError("s-a cerut o pagina in dry run")

        jurnal = []
        raport = ia_lotul(
            [anunt("a1"), anunt("a2")], cititor_care_explodeaza,
            self._salveaza_noteaza(jurnal), SURSE, ACUM, zile=30, limita=30, dry_run=True,
        )

        self.assertEqual(raport["cerute"], 0)
        self.assertEqual(jurnal, [])
        self.assertEqual(raport["de_procesat"], 2)
        self.assertEqual(raport["ar_procesa"], 2)

    def test_limita_opreste_la_N(self):
        """Cu limita 2 si 5 eligibile, se cer cel mult 2 pagini. Restul asteapta."""
        anunturi = [anunt(f"a{i}") for i in range(5)]
        cerute = []

        def cititor_care_numara(adresa):
            cerute.append(adresa)
            return cititor_ejobs_bun(adresa)

        raport = ia_lotul(
            anunturi, cititor_care_numara, self._salveaza_noteaza([]),
            SURSE, ACUM, zile=30, limita=2, dry_run=False,
        )

        self.assertEqual(len(cerute), 2)
        self.assertEqual(raport["cerute"], 2)
        self.assertEqual(raport["oprite_de_limita"], 3)

    def test_raportul_numara_fiecare_fel_de_rezultat(self):
        """Fiecare fel de raspuns ajunge in propria casuta din raport, nu intr-un total."""
        raport = ia_lotul(
            [anunt("bun")], cititor_ejobs_bun, self._salveaza_noteaza([]),
            SURSE, ACUM, zile=30, limita=30, dry_run=False,
        )
        self.assertEqual(raport["cu_descriere"], 1)

        raport = ia_lotul(
            [anunt("mort")], cititor_pagina_expirata, self._salveaza_noteaza([]),
            SURSE, ACUM, zile=30, limita=30, dry_run=False,
        )
        self.assertEqual(raport["expirate"], 1)

        raport = ia_lotul(
            [anunt("strain")], cititor_pagina_straina, self._salveaza_noteaza([]),
            SURSE, ACUM, zile=30, limita=30, dry_run=False,
        )
        self.assertEqual(raport["fara_descriere"], 1)

    def test_esecul_de_retea_opreste_lotul_si_nu_marcheaza_nimic(self):
        """
        Plasa cea mai importanta: o sursa care blocheaza nu are voie sa "consume" lotul.

        Fara ea, o blocare la primul anunt ar marca 30 de anunturi drept lipsite de
        descriere - si nimeni nu le-ar mai cere pagina vreodata.
        """
        anunturi = [anunt("a1"), anunt("a2"), anunt("a3")]
        cerute = []

        def cititor_care_blocheaza(adresa):
            cerute.append(adresa)
            raise EroareRetea("a raspuns cu 403 - nu s-a ajuns la pagina")

        jurnal = []
        raport = ia_lotul(
            anunturi, cititor_care_blocheaza, self._salveaza_noteaza(jurnal),
            SURSE, ACUM, zile=30, limita=30, dry_run=False,
        )

        self.assertEqual(len(cerute), 1)
        self.assertEqual(raport["cerute"], 0)
        self.assertEqual(jurnal, [])
        self.assertEqual(raport["esuate_retea"], 1)
        self.assertIn("403", raport["esec_retea"])

    def test_anuntul_expirat_NU_opreste_lotul(self):
        """Perechea testului de sus: un fapt despre anunt nu opreste nimic."""
        anunturi = [anunt("a1"), anunt("a2")]
        jurnal = []

        raport = ia_lotul(
            anunturi, cititor_pagina_expirata, self._salveaza_noteaza(jurnal),
            SURSE, ACUM, zile=30, limita=30, dry_run=False,
        )

        self.assertEqual(raport["cerute"], 2)
        self.assertEqual(raport["expirate"], 2)
        self.assertIsNone(raport["esec_retea"])
        self.assertEqual(len(jurnal), 2)

    def test_se_salveaza_ce_a_apucat_inainte_de_blocare(self):
        """Ce s-a scris cu succes inainte de esec ramane scris. Nu se pierde munca."""
        anunturi = [anunt("a1"), anunt("a2"), anunt("a3")]
        apeluri = []

        def cititor_care_cade_al_doilea(adresa):
            apeluri.append(adresa)
            if len(apeluri) == 1:
                return cititor_ejobs_bun(adresa)
            raise EroareRetea("blocat dupa prima cerere")

        jurnal = []
        raport = ia_lotul(
            anunturi, cititor_care_cade_al_doilea, self._salveaza_noteaza(jurnal),
            SURSE, ACUM, zile=30, limita=30, dry_run=False,
        )

        self.assertEqual(raport["cerute"], 1)
        self.assertEqual(raport["cu_descriere"], 1)
        self.assertEqual([rand[0] for rand in jurnal], ["a1"])
        self.assertEqual(raport["esuate_retea"], 1)


class TestFirmaSiTitluDinPagina(unittest.TestCase):
    """
    Firma si titlul real, luate din aceleasi date structurate ca descrierea.

    De ce e nevoie: din mailurile BestJobs de la sablonul 2026, firma nu se poate afla
    (e o poza fara text), iar titlul vine cu mobilierul cardului lipit de el. Pe pagina,
    amandoua stau scrise separat.
    """

    def test_bestjobs_da_firma_si_titlul_curat(self):
        rezultat = extrage_firma_si_titlul(
            pagina("bestjobs_multilingual_hrbp.html"), "bestjobs"
        )

        self.assertTrue(rezultat["ok"], rezultat.get("motiv"))
        self.assertEqual(rezultat["firma"], "MIND AUTOMOBILE PART ROMANIA S.R.L.")
        self.assertEqual(rezultat["titlu"], "Multilingual HRBP (Business Partner)")

    def test_ejobs_da_firma_si_titlul_din_schema_org(self):
        rezultat = extrage_firma_si_titlul(
            pagina("ejobs_senior_hr_business_partner.html"), "ejobs"
        )

        self.assertTrue(rezultat["ok"], rezultat.get("motiv"))
        self.assertEqual(rezultat["firma"], "ITWORX INTERNATIONAL SRL")
        self.assertIn("Senior Business Partner", rezultat["titlu"])

    def test_pagina_straina_e_esec_motivat(self):
        """Structura nerecunoscuta -> motiv, niciodata campuri goale care par date."""
        rezultat = extrage_firma_si_titlul("<html><body>nimic</body></html>", "bestjobs")

        self.assertFalse(rezultat["ok"])
        self.assertIn("__NEXT_DATA__", rezultat["motiv"])
        self.assertNotIn("firma", rezultat)

    def test_jumatate_gasita_se_respinge_intreaga(self):
        """
        Titlu fara firma = structura nu e cea pe care o credem. Respingem perechea
        intreaga, ca la validarea raspunsurilor de model: nu completam pe jumatate.
        """
        html = ('<script type="application/ld+json">'
                '{"@type":"JobPosting","title":"Ceva"}</script>')
        rezultat = extrage_firma_si_titlul(html, "ejobs")

        self.assertFalse(rezultat["ok"])
        self.assertIn("firma", rezultat["motiv"])


class TestTitlulDePastrat(unittest.TestCase):
    """
    Cand are voie pagina sa rescrie un titlu citit din mail. Raspunsul scurt: aproape
    niciodata - `titlu` e data BRUTA. Singurul caz permis e cel demonstrabil.
    """

    def test_mailul_cu_mobilier_lipit_se_inlocuieste(self):
        din_pagina = titlul_de_pastrat(
            "Multilingual HRBP (Business Partner) MIND AUTOMOBILE PART ROMANIA SRL",
            "Multilingual HRBP (Business Partner)",
        )

        self.assertEqual(din_pagina, "Multilingual HRBP (Business Partner)")

    def test_titluri_diferite_nu_se_ating(self):
        """
        Pagina in alta limba decat mailul: nu stim care e mai bun, deci nu atingem
        nimic. Un "seamana destul" ar fi inceputul rescrierii datelor dupa ureche.
        """
        self.assertEqual(
            titlul_de_pastrat("HR Generalist", "Specialist Resurse Umane"), ""
        )

    def test_titlu_identic_nu_se_atinge(self):
        """Nimic de castigat dintr-o scriere care nu schimba nimic."""
        self.assertEqual(titlul_de_pastrat("HR Generalist", "HR Generalist"), "")

    def test_titlul_din_pagina_mai_lung_nu_castiga(self):
        """Doar taierea unei cozi e permisa, nu adaugarea de text."""
        self.assertEqual(
            titlul_de_pastrat("HR Generalist", "HR Generalist with German"), ""
        )


if __name__ == "__main__":
    unittest.main()
