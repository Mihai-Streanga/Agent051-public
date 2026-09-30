r"""
Teste pentru core/briefing.py - distilarea PURA.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

UITA-TE CE NU E AICI.
Nicio baza de date, niciun fisier, niciun model - nici macar unul inventat. Celelalte
suite de teste ale proiectului injecteaza cel putin o functie `cheama_model` falsa.
Aici nu exista una, fiindca nu exista nimic care sa o ceara: briefingul se calculeaza
din datele primite ca parametru.

Anunturile de mai jos sunt inventate integral. Niciun titlu, nicio firma si niciun link
nu vin din baza reala.

CE VERIFICA, DE FAPT, TESTELE ASTEA:
ca briefingul spune ADEVARUL DISTILAT - taie ce nu merita aratat, dar numara tot ce a
taiat. Un briefing care ascunde in tacere un anunt e mai rau decat unul lung: pe al
doilea il citesti cu efort, pe primul te bazezi si nu afli niciodata ce ai ratat.
"""

import socket
import sys
import unittest
from pathlib import Path

# Codul proiectului sta in src/. Ii aratam lui Python calea.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.core import briefing as modul_briefing
from agent051.core.briefing import (
    MAXIM_IN_LISTA,
    compune_briefing,
    formateaza_text,
)


def anunt(
    id_anunt: str,
    verdict: str = "trece",
    relevant: str = "ideal",
    interes: str = "ridicat",
    spof: str = "nu",
    data_extragere: str = "2026-07-20T10:00:00+00:00",
    motive_respingere: list = None,
    are_evaluare_oarecare: bool = None,
    motive_coada: list = None,
) -> dict:
    """
    Un anunt inventat, cu valori implicite bune.

    Fiecare test schimba doar campul care il intereseaza, iar restul raman rezonabile.
    Asa se vede din apel ce anume testeaza: `anunt("X", verdict="respins")` spune
    limpede ca respingerea e subiectul, nu titlul sau firma.

    `relevant=None` inseamna ce inseamna si in baza: n-are verdict calitativ pe versiunea
    de criterii de acum. Ce s-a intamplat de fapt spune `are_evaluare_oarecare`:
        False - n-a fost evaluat niciodata
        True  - a fost, dar pe alte criterii (sau incercarea a fost respinsa)
    Implicit se deduce din `relevant`, ca sa nu trebuiasca scris in testele care nu-l
    privesc.
    """
    if are_evaluare_oarecare is None:
        are_evaluare_oarecare = relevant is not None

    return {
        "are_evaluare_oarecare": are_evaluare_oarecare,
        "id": id_anunt,
        "titlu": f"Rol inventat {id_anunt}",
        "firma": f"Firma {id_anunt}",
        "link": f"https://exemplu.invalid/{id_anunt}",
        "data_extragere": data_extragere,
        "verdict": verdict,
        "motive_respingere": motive_respingere or [],
        "relevant": relevant,
        "motiv_relevanta": "Motiv inventat pentru test." if relevant else None,
        "interes": interes,
        "motiv_interes": "Motiv inventat pentru test.",
        "single_point_of_failure": spof,
        "motive_coada": motive_coada or [],
    }


SURSE_CU_PAGINA = ("ejobs", "bestjobs")


def stadiu(
    sursa: str = "ejobs",
    are_link: int = 1,
    are_descriere: int = 1,
    status_pagina: str = "ok",
    status_normalizare: str = "ok",
    verdict: str = "trece",
    are_evaluare_valabila: int = 1,
    recent: bool = True,
) -> dict:
    """
    Stadiul unui anunt asupra caruia s-a facut TOT. Adica: nimic in asteptare.

    Implicitele sunt anume asa - un anunt asezat, care nu mai are nimic de facut pe el.
    Fiecare test de mai jos strica exact un lucru, si atunci din apel se citeste ce
    anume testeaza: `stadiu(status_normalizare=None)` spune limpede ca normalizarea
    lipsa e subiectul.

    Campurile sunt cele pe care le aduce stadiul_anunturilor() din store/db.py; `recent`
    se adauga peste ele in adapters/briefing.py, fiindca cere ceasul.
    """
    return {
        "id": "inventat",
        "sursa": sursa,
        "data_anunt": "2026-08-15T08:00:00+00:00",
        "are_link": are_link,
        "are_descriere": are_descriere,
        "status_pagina": status_pagina,
        "status_normalizare": status_normalizare,
        "verdict": verdict,
        "are_evaluare_valabila": are_evaluare_valabila,
        "recent": recent,
    }


def date(
    anunturi: list,
    mesaje_noi: int = 1,
    de_la: str = "2026-07-19T08:00:00+00:00",
    stadii: list = None,
):
    """Ambalajul pe care il primeste compune_briefing, cu valori implicite."""
    return {
        "de_la": de_la,
        "mesaje_noi": mesaje_noi,
        "anunturi": anunturi,
        "stadii": stadii or [],
        "surse_cu_pagina": SURSE_CU_PAGINA,
    }


class TestNimicNou(unittest.TestCase):

    def test_fara_mesaje_si_fara_anunturi_e_nimic_nou(self):
        rezultat = compune_briefing(date([], mesaje_noi=0))

        self.assertTrue(rezultat["nimic_nou"])
        self.assertEqual(rezultat["anunturi_noi"], 0)

    def test_textul_pentru_nimic_nou_e_o_singura_propozitie(self):
        """
        Un rand, nu un raport cu zerouri.

        Daca ai citi "0 mesaje noi, 0 anunturi noi, filtrul a respins 0...", ti-ar lua
        trei randuri ca sa afli ca nu s-a intamplat nimic. Asta e exact munca pe care
        briefingul trebuie sa o faca in locul tau.
        """
        text = formateaza_text(compune_briefing(date([], mesaje_noi=0)))

        self.assertEqual(len(text.splitlines()), 1)
        self.assertIn("Nimic nou", text)

    def test_anunturi_fara_niciunul_bun_NU_e_nimic_nou(self):
        """
        S-au intamplat lucruri, doar ca niciunul bun. Aia nu e "nimic nou".

        Distinctia conteaza: "nimic nou" inseamna liniste pe surse. "12 anunturi, toate
        respinse" inseamna ca sursele merg, dar criteriile taie tot - iar aia e o
        informatie despre CRITERII, care se poate actiona. Confundate, ai crede ca
        alertele de job s-au oprit.
        """
        respinse = [anunt(f"R{i}", verdict="respins") for i in range(12)]

        rezultat = compune_briefing(date(respinse, mesaje_noi=3))

        self.assertFalse(rezultat["nimic_nou"])
        self.assertEqual(rezultat["respinse"]["total"], 12)
        self.assertEqual(rezultat["merita_atentie"], [])


class TestNumaratoare(unittest.TestCase):

    def test_respinsul_se_numara_dar_nu_apare_in_lista(self):
        """Trei anunturi, unul respins: apare la numaratoare, nu printre recomandari."""
        anunturi = [
            anunt("A"),
            anunt("B"),
            anunt("C", verdict="respins", motive_respingere=["locatie in afara zonei: 'Cluj'"]),
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["anunturi_noi"], 3)
        self.assertEqual(rezultat["respinse"]["total"], 1)
        self.assertEqual(rezultat["respinse"]["motive"], {"locatie": 1})

        id_uri = [a["id"] for a in rezultat["merita_atentie"]]
        self.assertEqual(id_uri, ["A", "B"])
        self.assertNotIn("C", id_uri)

    def test_incertele_se_numara_separat(self):
        """Au trecut filtrul, dar cu date lipsa. Se arata, si se si numara ca atare."""
        anunturi = [anunt("A"), anunt("B", verdict="incert")]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["incerte"], 1)
        self.assertIn("B", [a["id"] for a in rezultat["merita_atentie"]])

    def test_motivele_de_respingere_se_grupeaza_pe_eticheta(self):
        """
        Cuvantul exclus devine el insusi eticheta; restul se scurteaza.

        "cuvant gasit: 'on-call' (in titlu)" numarat ca "cuvant gasit" n-ar spune nimic.
        Numarat ca "on-call" iti spune ce anume taie cel mai des - si daca vrei sa mai
        tii cuvantul ala pe lista.
        """
        anunturi = [
            anunt("A", verdict="respins", motive_respingere=["cuvant gasit: 'on-call' (in titlu)"]),
            anunt("B", verdict="respins", motive_respingere=["cuvant gasit: 'on-call' (in descriere)"]),
            anunt(
                "C",
                verdict="respins",
                motive_respingere=[
                    "venit sub pragul de respingere: max 4200 < 5000 RON ('4200 RON')"
                ],
            ),
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["respinse"]["motive"], {"on-call": 2, "venit": 1})

    def test_un_anunt_cu_doua_motive_se_numara_la_amandoua(self):
        """
        Suma motivelor poate depasi numarul respinselor. E corect si e intentionat.

        Intrebarea la care raspunde numaratoarea e "ce taie cel mai des", nu "cum se
        imparte totalul". Un anunt respins si pe locatie, si pe un cuvant exclus, e o
        dovada pentru amandoua regulile.
        """
        anunturi = [
            anunt(
                "A",
                verdict="respins",
                motive_respingere=[
                    "locatie in afara zonei: 'Cluj' (onsite), baza e Brasov",
                    "cuvant gasit: 'ture' (in titlu)",
                ],
            )
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["respinse"]["total"], 1)
        self.assertEqual(rezultat["respinse"]["motive"], {"locatie": 1, "ture": 1})


class TestExcluderi(unittest.TestCase):

    def test_singur_pe_proces_RAMANE_in_lista_cu_avertisment(self):
        """
        Pana la 29 sept. 2026, un rol care te-ar face singurul om pe un proces cu termen
        dur era scos din recomandari. Criteriul a fost scos: rolul ramane in lista, iar
        verdictul modelului se vede langa el, in structura si in text.
        """
        anunturi = [anunt("A"), anunt("B", spof="da")]

        rezultat = compune_briefing(date(anunturi))

        dupa_id = {a["id"]: a for a in rezultat["merita_atentie"]}
        self.assertEqual(sorted(dupa_id), ["A", "B"])
        self.assertEqual(dupa_id["B"]["singur_pe_proces"], "da")
        self.assertEqual(dupa_id["A"]["singur_pe_proces"], "nu")
        self.assertEqual(rezultat["excluse"]["total"], 0)
        self.assertNotIn("spof_da", rezultat["excluse"])

        text = formateaza_text(rezultat)
        self.assertIn("[singur pe proces]", text)
        self.assertEqual(text.count("[singur pe proces]"), 1)

    def test_treapta_exclus_e_scoasa_dar_numarata(self):
        anunturi = [anunt("A"), anunt("B", relevant="exclus")]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual([a["id"] for a in rezultat["merita_atentie"]], ["A"])
        self.assertEqual(rezultat["excluse"]["relevant_exclus"], 1)

    def test_treapta_din_mijloc_RAMANE_in_lista(self):
        """
        Testul care justifica intreaga schimbare 1.2.

        Pe scala binara, un "Senior HR Generalist" primea "relevant: nu" si disparea din
        recomandari. Acum sta pe treapta din mijloc, deci RAMANE in lista - mai jos decat
        un rol ideal, dar la vedere. Daca testul asta pica, filtrul taie iar prea lat.
        """
        anunturi = [anunt("A", relevant="bun_in_domeniu")]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual([a["id"] for a in rezultat["merita_atentie"]], ["A"])
        self.assertEqual(rezultat["excluse"]["total"], 0)

    def test_treapta_exclus_ramane_exclusa_si_cand_e_singur_pe_proces(self):
        """Excluderea vine doar din treapta; verdictul despre proces nu o schimba."""
        anunturi = [anunt("A", relevant="exclus", spof="da")]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["merita_atentie"], [])
        self.assertEqual(rezultat["excluse"], {"total": 1, "relevant_exclus": 1})


class TestLimita(unittest.TestCase):

    def test_zece_anunturi_bune_dau_cel_mult_cinci(self):
        """Peste cinci, lista redevine o lista de parcurs - adica problema initiala."""
        anunturi = [anunt(f"A{i}") for i in range(10)]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(len(rezultat["merita_atentie"]), MAXIM_IN_LISTA)
        self.assertEqual(rezultat["anunturi_noi"], 10)

    def test_textul_ramane_scurt_chiar_cu_lista_plina(self):
        """
        Cel mult 6 randuri, oricat de multe anunturi ar fi.

        Un briefing de 15 randuri nu se citeste - se amana. Ce nu incape in text ramane
        in structura, iar textul spune cate au mai fost.
        """
        anunturi = [anunt(f"A{i}") for i in range(10)]

        text = formateaza_text(compune_briefing(date(anunturi)))

        self.assertLessEqual(len(text.splitlines()), 6)
        self.assertIn("si inca", text)


class TestRepostari(unittest.TestCase):
    """
    Acelasi job, repus de firma sau de un agregator, nu apare ca doua noutati.
    Cazurile sunt cele gasite in baza pe 30 septembrie 2026 (Continental, Undelucram.ro).
    """

    def _job(self, id_anunt, firma, data_anunt, titlu="Business Owner Core HR"):
        return dict(anunt(id_anunt), titlu=titlu, firma=firma, data_anunt=data_anunt)

    def test_acelasi_titlu_si_firma_iese_pe_un_rand_cu_prima_data(self):
        anunturi = [
            self._job("vechi", "Continental", "2026-09-08T08:00:00+00:00"),
            self._job("nou", "continental ", "2026-09-23T08:00:00+00:00"),
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(len(rezultat["merita_atentie"]), 1)
        self.assertEqual(rezultat["merita_atentie"][0]["repostat_de_la"], "2026-09-08")
        self.assertEqual(rezultat["repostate_strase"], 1)
        self.assertIn("Repostari stranse sub acelasi rand: 1", formateaza_text(rezultat))

    def test_repostarea_unui_job_din_briefingul_trecut_se_vede(self):
        """Primul anunt nu e in briefingul de acum, ci doar printre cele recente."""
        de_acum = [self._job("nou", "Continental", "2026-09-23T08:00:00+00:00")]
        recente = [self._job("vechi", "Continental", "2026-09-08T08:00:00+00:00")]

        rezultat = compune_briefing(dict(date(de_acum), recente=recente))

        rand = rezultat["merita_atentie"][0]
        self.assertEqual(rand["repostat_de_la"], "2026-09-08")
        self.assertEqual(rezultat["repostate_strase"], 0)
        self.assertIn("[repostat, apare din 2026-09-08]", formateaza_text(rezultat))

    def test_alta_firma_ramane_pe_randul_ei_cu_eticheta(self):
        """
        Un titlu generic la doua firme e de obicei doua joburi: nu se ascunde niciunul,
        doar se spune ca pot fi acelasi.
        """
        anunturi = [
            self._job("firma", "Continental", "2026-09-08T08:00:00+00:00"),
            self._job("agregator", "Undelucram.ro", "2026-09-09T08:00:00+00:00"),
        ]

        rezultat = compune_briefing(dict(date(anunturi), agregatori=("undelucram.ro",)))

        self.assertEqual(len(rezultat["merita_atentie"]), 2)
        pe_id = {rand["id"]: rand for rand in rezultat["merita_atentie"]}
        self.assertEqual(pe_id["agregator"]["posibil_repostat"], ["Continental"])
        self.assertIsNone(pe_id["agregator"]["repostat_de_la"])
        self.assertIn("[posibil repostat: Undelucram.ro]", formateaza_text(rezultat))

    def test_titlul_generic_fara_agregator_nu_primeste_eticheta(self):
        """
        "Human Resources Specialist" la sase firme sunt sase joburi. Pe date reale,
        eticheta ajunsese la liste de sase firme - de-asta cere un agregator.
        """
        anunturi = [
            self._job("unu", "G-P", "2026-09-10T08:00:00+00:00", titlu="HR Specialist"),
            self._job("doi", "Webuild", "2026-09-11T08:00:00+00:00", titlu="HR Specialist"),
        ]

        rezultat = compune_briefing(dict(date(anunturi), agregatori=("undelucram.ro",)))

        self.assertEqual(len(rezultat["merita_atentie"]), 2)
        for rand in rezultat["merita_atentie"]:
            self.assertEqual(rand["posibil_repostat"], [])

    def test_un_job_unic_nu_primeste_eticheta(self):
        rezultat = compune_briefing(date([anunt("singur")]))

        rand = rezultat["merita_atentie"][0]
        self.assertIsNone(rand["repostat_de_la"])
        self.assertEqual(rand["posibil_repostat"], [])
        self.assertNotIn("repost", formateaza_text(rezultat))

    def test_oportunitatile_au_aceleasi_etichete_ca_briefingul(self):
        """
        Unealta oportunitati_noi foloseste aceeasi strangere. Pana la 30 sept. 2026 nu
        primea agregatorii si anunturile recente, deci nu arata niciodata "posibil repostat".
        """
        anunturi = [self._job("agregator", "Undelucram.ro", "2026-09-09T08:00:00+00:00")]
        recente = [self._job("vechi", "Continental", "2026-09-08T08:00:00+00:00")]

        rand = modul_briefing.alege_oportunitatile(
            anunturi, 10, recente, ("undelucram.ro",)
        )[0]

        self.assertEqual(rand["posibil_repostat"], ["Continental"])


class TestSortare(unittest.TestCase):

    def test_ordinea_de_prioritate_e_respectata_nivel_cu_nivel(self):
        """
        Verifica explicit ca fiecare criteriu bate pe urmatorul.

        Cele patru anunturi sunt construite anume ca fiecare sa fie cel mai bun pe un
        nivel si mai slab pe altul. Daca ordinea criteriilor s-ar inversa undeva,
        rezultatul ar fi altul - deci testul prinde chiar inversarea, nu doar o
        sortare "cam pe acolo".

            D  trece  / ideal  / ridicat   -> primul, cel mai bun peste tot
            C  trece  / ideal  / mediu     -> pierde doar la interes
            B  trece  / incert / ridicat   -> pierde la relevanta, desi are interes maxim
            A  incert / ideal  / ridicat   -> pierde la verdict, desi restul e maxim
        """
        anunturi = [
            anunt("A", verdict="incert", relevant="ideal", interes="ridicat"),
            anunt("B", verdict="trece", relevant="incert", interes="ridicat"),
            anunt("C", verdict="trece", relevant="ideal", interes="mediu"),
            anunt("D", verdict="trece", relevant="ideal", interes="ridicat"),
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(
            [a["id"] for a in rezultat["merita_atentie"]], ["D", "C", "B", "A"]
        )

    def test_treptele_de_relevanta_se_aseaza_in_ordine(self):
        """
        ideal > bun_in_domeniu > incert, la interes egal.

        "incert" sta SUB treapta din mijloc, nu peste: un rol despre care modelul a putut
        spune ceva - fie si "e doar in domeniu" - se uita inaintea unuia din care n-a
        putut spune nimic (de obicei, un anunt fara descriere).
        """
        anunturi = [
            anunt("INCERT", relevant="incert"),
            anunt("MIJLOC", relevant="bun_in_domeniu"),
            anunt("IDEAL", relevant="ideal"),
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(
            [a["id"] for a in rezultat["merita_atentie"]],
            ["IDEAL", "MIJLOC", "INCERT"],
        )

    def test_la_prioritati_egale_cele_mai_recente_sunt_primele(self):
        anunturi = [
            anunt("VECHI", data_extragere="2026-07-01T10:00:00+00:00"),
            anunt("NOU", data_extragere="2026-07-22T10:00:00+00:00"),
            anunt("MIJLOC", data_extragere="2026-07-10T10:00:00+00:00"),
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(
            [a["id"] for a in rezultat["merita_atentie"]], ["NOU", "MIJLOC", "VECHI"]
        )

    def test_anuntul_neevaluat_ajunge_la_coada_nu_la_cap(self):
        """
        Un anunt fara verdicte calitative (inca neevaluat) nu se strecoara in fata.

        Daca necunoscutul ar primi rangul cel mai bun, un anunt despre care nu stim
        nimic ar sari peste unul pe care modelul l-a numit relevant si interesant.
        Il aratam - e o oportunitate reala - dar ultimul.
        """
        anunturi = [
            anunt("NEEVALUAT", relevant=None, interes=None),
            anunt("EVALUAT", relevant="ideal", interes="ridicat"),
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(
            [a["id"] for a in rezultat["merita_atentie"]], ["EVALUAT", "NEEVALUAT"]
        )

    def test_motivele_de_coada_bat_orice_alt_criteriu(self):
        """
        Birou toata saptamana sau salariu sub prag_trecere =
        trece, dar la coada. Chiar si un "ideal / ridicat" ajunge dupa un "incert",
        iar textul spune de ce.
        """
        anunturi = [
            anunt("BIROU", motive_coada=["birou toata saptamana, peste 2 zile"]),
            anunt("SLAB", verdict="incert", relevant="incert", interes="scazut"),
        ]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(
            [a["id"] for a in rezultat["merita_atentie"]], ["SLAB", "BIROU"]
        )
        dupa_id = {a["id"]: a for a in rezultat["merita_atentie"]}
        self.assertEqual(dupa_id["SLAB"]["la_coada"], [])
        self.assertIn(
            "[la coada: birou toata saptamana, peste 2 zile]", formateaza_text(rezultat)
        )

    def test_acelasi_set_de_date_da_acelasi_rezultat(self):
        """
        Determinismul, verificat direct.

        Doua apeluri pe aceleasi date trebuie sa dea acelasi lucru, la virgula. Asta e
        promisiunea pe care un model chemat aici ar strica-o: acelasi set de anunturi ar
        produce doua rezumate diferite, si n-ai mai putea pune doua rulari alaturi ca sa
        vezi ce s-a schimbat de fapt.
        """
        anunturi = [
            anunt("A", interes="mediu"),
            anunt("B", verdict="incert"),
            anunt("C", data_extragere="2026-07-21T10:00:00+00:00"),
        ]

        intai = compune_briefing(date(anunturi))
        adoua = compune_briefing(date(anunturi))

        self.assertEqual(intai, adoua)
        self.assertEqual(formateaza_text(intai), formateaza_text(adoua))


class TestPuritate(unittest.TestCase):
    """
    Dovada ca briefingul nu iese nicaieri: nici pe retea, nici pe disc, nici la un model.

    Regula proiectului spune ca `core/` trebuie sa mearga cu internetul taiat si fara
    niciun fisier. Testele de mai jos nu se bazeaza pe citirea codului, ci il pun in
    situatia respectiva si verifica ce se intampla.
    """

    def test_functioneaza_cu_reteaua_taiata(self):
        """
        Taiem `socket` la radacina si rulam briefingul. Daca ar chema ceva, ar crapa.

        Nu e o metafora: dupa inlocuirea de mai jos, ORICE incercare de conexiune din
        procesul asta - un client HTTP, un SDK de model, o cerere ascunsa intr-o
        biblioteca - arunca o exceptie. Briefingul trece nemiscat.
        """
        socket_original = socket.socket

        def refuza_orice_conexiune(*argumente, **parametri):
            raise AssertionError(
                "core/briefing.py a incercat sa deschida o conexiune de retea"
            )

        socket.socket = refuza_orice_conexiune
        try:
            rezultat = compune_briefing(date([anunt("A"), anunt("B", verdict="respins")]))
            text = formateaza_text(rezultat)
        finally:
            socket.socket = socket_original

        self.assertEqual(rezultat["anunturi_noi"], 2)
        self.assertTrue(text)

    def test_modulul_nu_importa_nimic(self):
        """
        Lista de importuri a lui core/briefing.py trebuie sa fie GOALA.

        Testul asta e mai tare decat "nu cheama un model": verifica sa nu existe nici
        macar unealta cu care ar putea sa o faca. Fara `json`, `sqlite3`, `datetime` sau
        vreun client - nimic care sa atinga discul, ceasul sau reteaua.

        `datetime` merita o vorba: n-ar atinge reteaua, dar ar face briefingul
        dependent de momentul rularii, deci nereproductibil. Momentele vin din date,
        primite ca parametru.
        """
        module_importate = [
            nume
            for nume, valoare in vars(modul_briefing).items()
            if not nume.startswith("__") and type(valoare).__name__ == "module"
        ]

        self.assertEqual(module_importate, [])

    def test_nu_primeste_si_nu_cere_nicio_functie_de_model(self):
        """
        Semnatura are un singur parametru: datele. Niciun `cheama_model`.

        In restul proiectului, orice functie care are nevoie de judecata primeste
        modelul ca parametru. Absenta parametrului aici e contractul scris in cod:
        briefingul NU are voie sa ceara o judecata noua, fiindca toate judecatile au
        fost deja date si platite, la evaluare.
        """
        import inspect

        parametri = list(inspect.signature(compune_briefing).parameters)

        self.assertEqual(parametri, ["date"])


class TestLipsaEvaluarii(unittest.TestCase):
    """
    LIPSA NU E TACERE.

    De cand se citesc doar evaluarile date pe versiunea de criterii de acum, o urcare de
    versiune face TOATE verdictele vechi nevalabile deodata. Briefingul trebuie sa spuna
    cate anunturi au ramas fara verdict - altfel "n-am gasit nimic bun" si "n-am evaluat
    inca nimic" arata identic, desi cer lucruri opuse de la cine citeste.
    """

    def test_anuntul_fara_evaluare_se_numara(self):
        anunturi = [anunt("A"), anunt("B", relevant=None)]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["fara_evaluare"]["total"], 1)
        self.assertEqual(rezultat["fara_evaluare"]["niciodata"], 1)
        self.assertEqual(rezultat["fara_evaluare"]["de_reevaluat"], 0)

    def test_evaluarea_pe_criterii_vechi_se_numara_separat(self):
        """
        Doua cifre, fiindca duc la doua actiuni diferite: una cere o evaluare, cealalta
        o REevaluare - si atunci stii ca platesti a doua oara pentru acelasi anunt.
        """
        anunturi = [anunt("A", relevant=None, are_evaluare_oarecare=True)]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["fara_evaluare"]["total"], 1)
        self.assertEqual(rezultat["fara_evaluare"]["niciodata"], 0)
        self.assertEqual(rezultat["fara_evaluare"]["de_reevaluat"], 1)

    def test_respinsele_nu_intra_la_socoteala(self):
        """
        Un anunt respins de filtrul dur n-are de ce sa fie evaluat - modelul nici nu e
        chemat pe el. Ar fi un gol raportat degeaba, in fiecare briefing, pentru totdeauna.
        """
        anunturi = [anunt("A", verdict="respins", relevant=None)]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["fara_evaluare"]["total"], 0)

    def test_anuntul_neevaluat_ramane_in_lista_dar_la_coada(self):
        """
        Se numara, dar NU se ascunde: un anunt trecut de filtrul dur e o oportunitate
        reala despre care doar nu stim inca destul. Apare ultimul, nu deloc.
        """
        anunturi = [anunt("A", relevant=None), anunt("B", relevant="ideal")]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual([a["id"] for a in rezultat["merita_atentie"]], ["B", "A"])

    def test_textul_spune_de_ce_lipsesc(self):
        anunturi = [anunt("A", relevant=None), anunt("B", relevant=None, are_evaluare_oarecare=True)]

        text = formateaza_text(compune_briefing(date(anunturi)))

        self.assertIn("Fara verdict pe criteriile de acum: 2", text)
        self.assertIn("neevaluate: 1", text)
        self.assertIn("de reevaluat: 1", text)

    def test_baza_DOAR_cu_evaluari_vechi_nu_pare_goala(self):
        """
        CAZUL CARE A CERUT TOATA SCHIMBAREA. Ridici versiunea criteriilor: toate
        evaluarile devin nevalabile in aceeasi secunda.

        Briefingul NU are voie sa arate ca si cum n-ar exista oportunitati. Anunturile
        raman in lista (au trecut filtrul dur), iar textul spune limpede ca niciunul n-are
        verdict pe criteriile de acum. Diferenta dintre "nu e nimic" si "nu s-a evaluat".
        """
        anunturi = [
            anunt("A", relevant=None, are_evaluare_oarecare=True),
            anunt("B", relevant=None, are_evaluare_oarecare=True),
            anunt("C", relevant=None, are_evaluare_oarecare=True),
        ]

        rezultat = compune_briefing(date(anunturi))
        text = formateaza_text(rezultat)

        self.assertEqual(rezultat["fara_evaluare"]["de_reevaluat"], 3)
        self.assertEqual(len(rezultat["merita_atentie"]), 3)
        self.assertFalse(rezultat["nimic_nou"])
        self.assertIn("de reevaluat: 3", text)
        # Motivarea fiecarui anunt spune de ce n-are verdict, nu tace.
        self.assertTrue(
            all("fara verdict pe criteriile de acum" in a["motiv"] for a in rezultat["merita_atentie"])
        )

    def test_toate_evaluate_nu_raporteaza_niciun_gol(self):
        """Perechea testelor de mai sus: cand totul e evaluat, randul nici nu apare."""
        anunturi = [anunt("A"), anunt("B")]

        rezultat = compune_briefing(date(anunturi))

        self.assertEqual(rezultat["fara_evaluare"]["total"], 0)
        self.assertNotIn("Fara verdict", formateaza_text(rezultat))


class TestInAsteptare(unittest.TestCase):
    """
    BRIEFINGUL SPUNE CAND E INCOMPLET.

    Dupa reparatia taieturii, o ordine gresita a lantului nu mai pierde nimic - dar tot
    produce un raport care ARATA complet si nu e. Un briefing rulat inaintea evaluarii
    spune "nimic de semnalat" cu acelasi ton cu care l-ar spune dupa ce s-a judecat tot.
    Testele de aici verifica exact diferenta dintre cele doua.

    Fiecare cifra trebuie sa fie ACEEASI pe care ar face-o rularea etapei respective -
    de aia testele urmaresc, pe rand, plasele din adapters/: varsta la normalizare,
    sursa si pagina deja luata la descrieri, verdictul filtrului la evaluare.
    """

    def test_anuntul_recent_nenormalizat_se_numara(self):
        rezultat = compune_briefing(date([], stadii=[stadiu(status_normalizare=None)]))

        self.assertEqual(rezultat["in_asteptare"]["nenormalizate"], 1)
        self.assertEqual(rezultat["in_asteptare"]["total"], 1)

    def test_anuntul_VECHI_nenormalizat_nu_se_numara(self):
        """
        Plasa de varsta, aceeasi ca la normalizare.

        Fara ea, avertizarea ar spune "2858 nenormalizate" pe o arhiva de unsprezece ani
        care nu se normalizeaza niciodata, si ar deveni un rand pe care il ignori. O
        avertizare permanenta nu e o avertizare.
        """
        rezultat = compune_briefing(
            date([], stadii=[stadiu(status_normalizare=None, recent=False)])
        )

        self.assertEqual(rezultat["in_asteptare"]["nenormalizate"], 0)
        self.assertEqual(rezultat["in_asteptare"]["total"], 0)

    def test_anuntul_normalizat_respins_se_numara_din_nou(self):
        """
        Doar 'ok' inseamna facut. O incercare respinsa se reia - la fel ca la rulare.
        """
        rezultat = compune_briefing(
            date([], stadii=[stadiu(status_normalizare="respins")])
        )

        self.assertEqual(rezultat["in_asteptare"]["nenormalizate"], 1)

    def test_trecut_de_filtru_fara_evaluare_se_numara(self):
        rezultat = compune_briefing(
            date([], stadii=[stadiu(verdict="incert", are_evaluare_valabila=0)])
        )

        self.assertEqual(rezultat["in_asteptare"]["neevaluate"], 1)

    def test_respinsul_de_filtru_nu_asteapta_nicio_evaluare(self):
        """
        A picat pe o regula certa. Nu merge la model, deci nu e lucru nefacut - iar daca
        s-ar numara aici, avertizarea ar cere o cheltuiala care nu se va face niciodata.
        """
        rezultat = compune_briefing(
            date([], stadii=[stadiu(verdict="respins", are_evaluare_valabila=0)])
        )

        self.assertEqual(rezultat["in_asteptare"]["neevaluate"], 0)

    def test_nefiltratul_inca_nu_asteapta_o_evaluare(self):
        """Fara verdict de filtru, anuntul nici n-a ajuns la etapa evaluarii."""
        rezultat = compune_briefing(
            date([], stadii=[stadiu(verdict=None, are_evaluare_valabila=0)])
        )

        self.assertEqual(rezultat["in_asteptare"]["neevaluate"], 0)

    def test_anuntul_fara_descriere_de_la_o_sursa_cu_parser_se_numara(self):
        rezultat = compune_briefing(
            date([], stadii=[stadiu(are_descriere=0, status_pagina=None)])
        )

        self.assertEqual(rezultat["in_asteptare"]["fara_descriere"], 1)

    def test_linkedin_nu_asteapta_nicio_descriere(self):
        """
        LinkedIn nu e printre surse, deliberat - blocheaza cererile automate si nu ne
        deghizam. Un anunt de acolo e orb pentru totdeauna, si asta nu e lucru nefacut,
        ci o limita cunoscuta. Numarata aici, ar face avertizarea sa ceara ceva imposibil.
        """
        rezultat = compune_briefing(
            date(
                [],
                stadii=[stadiu(sursa="linkedin", are_descriere=0, status_pagina=None)],
            )
        )

        self.assertEqual(rezultat["in_asteptare"]["fara_descriere"], 0)

    def test_pagina_deja_luata_nu_se_mai_cere(self):
        """
        Pagina a venit, dar parserul n-a gasit textul (status 'ok' inseamna cerere
        reusita). Nu se mai cere o data: raspunsul ar fi acelasi.
        """
        rezultat = compune_briefing(
            date([], stadii=[stadiu(are_descriere=0, status_pagina="ok")])
        )

        self.assertEqual(rezultat["in_asteptare"]["fara_descriere"], 0)

    def test_anuntul_expirat_nu_mai_asteapta_nimic(self):
        """
        Datoria din 17 august 2026, vazuta din capatul celalalt.

        Trei anunturi moarte stateau permanent la `in_asteptare.fara_descriere`, deci
        randul "Briefingul e incomplet: fara descriere: 3" nu se stingea niciodata. Un
        avertisment care nu se poate stinge ajunge mobilier si nu mai avertizeaza.

        Regula trebuie sa fie ACEEASI ca in alege_anunturile (STATUSURI_INCHISE din
        adapters/descrieri.py): altfel avertizarea ar spune un numar si rularea altul.
        """
        rezultat = compune_briefing(
            date([], stadii=[stadiu(are_descriere=0, status_pagina="expirat")])
        )

        self.assertEqual(rezultat["in_asteptare"]["fara_descriere"], 0)
        self.assertEqual(rezultat["in_asteptare"]["total"], 0)

    def test_pagina_interzisa_de_robots_ramane_in_asteptare(self):
        """robots.txt se poate schimba, deci treaba nu e inchisa - si asa se si vede."""
        rezultat = compune_briefing(
            date([], stadii=[stadiu(are_descriere=0, status_pagina="interzis_robots")])
        )

        self.assertEqual(rezultat["in_asteptare"]["fara_descriere"], 1)

    def test_fara_link_nu_exista_pagina_de_cerut(self):
        rezultat = compune_briefing(
            date(
                [],
                stadii=[stadiu(are_link=0, are_descriere=0, status_pagina=None)],
            )
        )

        self.assertEqual(rezultat["in_asteptare"]["fara_descriere"], 0)

    def test_totalul_nu_e_suma_celor_trei(self):
        """
        Un anunt care asteapta si o descriere, si o normalizare, e UN anunt.

        Daca totalul ar aduna cifrele, o baza cu 60 de anunturi proaspete ar raporta
        "120 in asteptare" - o cifra care nu corespunde la nimic din baza si care face
        situatia sa para de doua ori mai grava decat e.
        """
        stadii = [
            stadiu(are_descriere=0, status_pagina=None, status_normalizare=None),
            stadiu(are_descriere=0, status_pagina=None, status_normalizare=None),
        ]

        rezultat = compune_briefing(date([], stadii=stadii))

        self.assertEqual(rezultat["in_asteptare"]["fara_descriere"], 2)
        self.assertEqual(rezultat["in_asteptare"]["nenormalizate"], 2)
        self.assertEqual(rezultat["in_asteptare"]["total"], 2)

    def test_textul_spune_ca_briefingul_e_incomplet(self):
        stadii = [stadiu(status_normalizare=None)] + [
            stadiu(verdict="trece", are_evaluare_valabila=0) for _ in range(3)
        ]

        text = formateaza_text(compune_briefing(date([anunt("A")], stadii=stadii)))

        self.assertIn("Atentie, briefingul e incomplet", text)
        self.assertIn("nenormalizate: 1", text)
        self.assertIn("neevaluate: 3", text)
        # Ce e pe zero nu se pomeneste - randul spune ce lipseste, nu ce nu lipseste.
        self.assertNotIn("fara descriere", text)

    def test_pe_o_baza_asezata_textul_nu_spune_nimic_in_plus(self):
        """Perechea testului de mai sus. Cand nu e nimic de facut, linistea e mesajul."""
        text = formateaza_text(
            compune_briefing(date([anunt("A")], stadii=[stadiu(), stadiu()]))
        )

        self.assertNotIn("incomplet", text)

    def test_avertizarea_apare_si_peste_NIMIC_NOU(self):
        """
        CAZUL PENTRU CARE EXISTA TOT CAPITOLUL.

        "Nimic nou" plus o coada de anunturi nejudecate se citeste, altfel, ca "nu mai e
        nimic de gasit" - adica exact concluzia gresita, trasa dintr-un raport corect.
        Aici, si numai aici, briefingul are voie sa aiba doua randuri cand nu e nimic nou.
        """
        rezultat = compune_briefing(
            date([], mesaje_noi=0, stadii=[stadiu(status_normalizare=None)])
        )
        text = formateaza_text(rezultat)

        self.assertTrue(rezultat["nimic_nou"])
        self.assertEqual(len(text.splitlines()), 2)
        self.assertIn("Nimic nou", text)
        self.assertIn("incomplet", text)

    def test_fara_stadii_nu_se_inventeaza_nicio_avertizare(self):
        """
        Un apelant care nu da stadii primeste zero, nu o presupunere.

        Briefingul nu ghiceste ce n-a fost intrebat: fara datele alea, singurul raspuns
        onest la "cat lucru a ramas?" e ca nu se stie, si atunci nu se spune nimic.
        """
        rezultat = compune_briefing({"de_la": None, "mesaje_noi": 0, "anunturi": []})

        self.assertEqual(rezultat["in_asteptare"]["total"], 0)
        self.assertNotIn("incomplet", formateaza_text(rezultat))


if __name__ == "__main__":
    unittest.main()
