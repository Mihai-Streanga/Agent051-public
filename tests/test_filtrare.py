r"""
Teste pentru core/filtrare.py - filtrul determinist pe constrangeri dure.

Rulare, din folderul proiectului:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

Niciun model, nicio retea, niciun fisier. Criteriile se INJECTEAZA ca dictionar, deci
testele nu citesc config/criterii.yaml - isi scriu singure regulile, mai jos. Asta
inseamna ca testele NU se strica atunci cand editezi criterii.yaml, si e intentionat:
altfel, ridicarea unui prag ti-ar face suita rosie fara ca vreun cod sa fie gresit.

CE VERIFICA, DE FAPT, FIECARE TEST DE MAI JOS:
ca lipsa unei date nu se transforma niciodata intr-o afirmatie.
Un filtru determinist gresit e mai periculos decat un model care halucineaza: taie
tacut, consecvent, si cu un motiv care arata rezonabil in raport. Un anunt bun respins
din greseala nu se mai uita nimeni la el niciodata.
"""

import sys
import unittest
from pathlib import Path

# Codul proiectului sta in src/. Ii aratam lui Python calea.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.core.filtrare import filtreaza_dur

# Criteriile de test. Aceeasi forma ca in criterii.yaml, dar cu valori proprii, ca
# testele sa nu depinda de ce scrie in fisierul real.
CRITERII = {
    "meta": {"versiune": "test"},
    "constrangeri_dure": {
        "venit_net_lunar_ron": {"prag_respingere": 5000},
        "locatie": {"baza": "Brașov", "remote_acceptat": True},
        "rol_structura": {
            "cuvinte_excluse": ["on-call", "ture", "gardă", "schimburi"]
        },
        # Aceeasi forma ca in criterii.yaml, dar cu o mana de limbi, nu cu toate:
        # testele verifica MECANISMUL (cum se combina listele), nu inventarul de limbi.
        "limbi": {
            "vorbite": ["romana", "engleza"],
            "scrieri": {
                "romana": ["romana", "romanian"],
                "engleza": ["engleza", "english"],
                "germana": ["germana", "german", "deutsch"],
                "franceza": ["franceza", "french"],
            },
            "tipare": ["with {limba}", "{limba} speaker", "cu {limba}"],
            "tipare_directe": ["multilingual"],
        },
    },
}


def anunt(**campuri) -> dict:
    """
    Fabrica un anunt normalizat, curat, peste care se pun modificarile cerute.

    Baza e dinadins un anunt care TRECE: asa, fiecare test schimba un singur lucru si
    se vede exact ce anume a produs verdictul.
    """
    baza = {
        "id": "anunt-test",
        "titlu": "Specialist Payroll",
        "firma": "Firma Inventata SRL",
        "locatie": "Brașov",
        "rol_normalizat": "Specialist Payroll",
        "tip_munca": "onsite",
        "descriere": "",
        "salariu_brut": "9000 RON",
    }
    baza.update(campuri)
    return baza


class TestVenit(unittest.TestCase):

    def test_sub_prag_e_respins(self):
        """salariu_brut '2500 RON' e sub prag, cu certitudine -> respins pe venit."""
        rezultat = filtreaza_dur(anunt(salariu_brut="2500 RON"), CRITERII)

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertEqual(len(rezultat["motive_respingere"]), 1)
        self.assertIn("2500", rezultat["motive_respingere"][0])

    def test_interval_cu_capul_de_sus_sub_prag_e_respins(self):
        """
        "3000 - 4000 RON": nici capatul de sus nu atinge pragul. Orice ar oferi firma
        e sub prag - certitudine. Respingem pe MAXIMUL intervalului.
        """
        rezultat = filtreaza_dur(anunt(salariu_brut="3000 - 4000 RON"), CRITERII)

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("4000", rezultat["motive_respingere"][0])

    def test_peste_prag_trece(self):
        rezultat = filtreaza_dur(anunt(salariu_brut="9000 RON"), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")

    def test_interval_care_atinge_pragul_nu_e_respins(self):
        """
        "3000 - 6000 RON": capatul de sus trece pragul. Firma poate plati si peste,
        deci NU respingem pe venit. Nu e "bun" - doar nu pica aici.
        """
        rezultat = filtreaza_dur(anunt(salariu_brut="3000 - 6000 RON"), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")

    def test_fara_salariu_nu_e_respins_ci_marcat(self):
        """
        Salariu neafisat = necunoscut NEBLOCANT: se noteaza, dar nu opreste "trece".

        Majoritatea anunturilor din Romania nu afiseaza salariul. Daca lipsa lui ar
        bloca verdictul, NICIUN anunt n-ar trece vreodata - si ar rata exact joburile
        bune, fiindca firmele serioase negociaza, nu publica grile. Anuntul de baza e
        curat pe restul (Brasov, onsite), deci iese "trece" - cu nota alaturi, nu
        "incert".
        """
        rezultat = filtreaza_dur(anunt(salariu_brut=""), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_respingere"], [])
        self.assertIn("salariu neafisat in anunt", rezultat["necunoscute"])

    def test_salariu_ambiguu_e_necunoscut_nu_respins(self):
        """
        "salariu motivant" nu are nicio cifra. Nu ghicim ce inseamna.

        Cazul cerut explicit: un text de salariu ambiguu e NEBLOCANT - se noteaza, dar
        lasa "trece". Nu respins, si nici macar "incert": salariul nu blocheaza.
        """
        rezultat = filtreaza_dur(anunt(salariu_brut="salariu motivant"), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_respingere"], [])
        self.assertTrue(
            any("neinterpretabil" in n for n in rezultat["necunoscute"])
        )

    def test_salariu_in_euro_e_necunoscut_nu_respins(self):
        """
        CAZUL CARE PAZESTE ARHIVA. Toate salariile afisate in arhiva sunt in EURO
        ("1600 - 1900€"). Numarul 1600 e sub 5000 - dar 1600 € NU sunt 1600 RON.
        Conversia depinde de un curs care se schimba; a compara ar insemna a ghici.

        Fara regula asta, filtrul ar respinge gresit aproape fiecare anunt BestJobs.
        Deci: valuta straina -> necunoscut NEBLOCANT, niciodata respins. Anuntul de
        baza fiind curat pe rest, iese "trece", cu nota valutei alaturi.
        """
        rezultat = filtreaza_dur(anunt(salariu_brut="1600 - 1900€"), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_respingere"], [])
        self.assertTrue(
            any("valuta straina" in n for n in rezultat["necunoscute"])
        )

    def test_salariu_pe_ora_e_necunoscut_nu_respins(self):
        """
        "50 RON/ora": numarul 50 e sub prag - dar pragul e LUNAR, iar 50 RON/ora
        inseamna ~8000 RON/luna. Necomparabil -> necunoscut NEBLOCANT, nu respins,
        si nu blocheaza: anuntul curat pe rest trece.
        """
        rezultat = filtreaza_dur(anunt(salariu_brut="50 RON/ora"), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_respingere"], [])

    def test_salariu_fara_moneda_e_necunoscut_nu_respins(self):
        """
        Un numar gol de moneda ("2500", fara RON/€) nu spune in ce e exprimat. Ar
        putea fi 2500 € - a-l respinge ca 2500 RON ar fi o eroare. Nu ghicim, si nici
        nu blocam pe asta: e necunoscut NEBLOCANT, deci anuntul curat pe rest trece.
        """
        rezultat = filtreaza_dur(anunt(salariu_brut="2500"), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_respingere"], [])

    def test_exact_pe_prag_nu_e_respins(self):
        """
        Pragul se numeste "prag_respingere": respinge ce e SUB el.

        Exact 5000 nu e sub 5000. Testul asta pare marunt, dar erorile de tipul
        "< versus <=" sunt printre cele mai usoare de scris gresit si cele mai greu
        de observat dupa - ar respinge tacut fix anunturile de la limita.
        """
        rezultat = filtreaza_dur(anunt(salariu_brut="5000 RON"), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")


class TestLocatie(unittest.TestCase):

    def test_alt_oras_onsite_e_respins(self):
        rezultat = filtreaza_dur(
            anunt(locatie="București", tip_munca="onsite"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("București", rezultat["motive_respingere"][0])

    def test_remote_trece_indiferent_de_oras(self):
        """
        criterii.yaml spune remote_locatie_firma_irelevanta. Daca lucrezi de acasa,
        unde sta firma nu te priveste.
        """
        rezultat = filtreaza_dur(
            anunt(locatie="București", tip_munca="remote"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "trece")

    def test_orasul_de_baza_trece(self):
        rezultat = filtreaza_dur(
            anunt(locatie="Brașov", tip_munca="onsite"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "trece")

    def test_diacriticele_nu_conteaza(self):
        """
        "Brasov" fara diacritice e acelasi oras.

        Platformele il scriu in toate felurile. O comparatie pe text brut ar rata
        potrivirea si ar respinge anuntul ca fiind "in alt oras" - tacut, si cu un
        motiv care ar parea perfect corect in raport.
        """
        rezultat = filtreaza_dur(
            anunt(locatie="Brasov", tip_munca="onsite"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "trece")

    def test_fara_locatie_e_incert_nu_respins(self):
        rezultat = filtreaza_dur(
            anunt(locatie="", tip_munca="onsite"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "incert")
        self.assertEqual(rezultat["motive_respingere"], [])
        self.assertIn("locatie neprecizata in anunt", rezultat["necunoscute"])

    def test_alt_oras_fara_fel_de_munca_e_incert(self):
        """
        DECIZIE, nu scapare: "București" + tip_munca necunoscut = incert, nu respins.

        Un rol remote listat pe sediul firmei arata exact asa. Daca l-am respinge, am
        arunca joburi bune fara sa aflam vreodata - un anunt respins nu se mai citeste.
        Costul acestei alegeri e o listare in plus de citit; costul celeilalte ar fi
        fost o oportunitate pierduta in tacere.
        """
        rezultat = filtreaza_dur(
            anunt(locatie="București", tip_munca="nespecificat"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "incert")
        self.assertEqual(rezultat["motive_respingere"], [])


class TestCuvinteExcluse(unittest.TestCase):

    def test_on_call_e_respins_cu_cuvantul_la_vedere(self):
        """
        Motivul spune EXACT ce cuvant a declansat respingerea si in ce camp.

        Fara asta, "respins pe structura rolului" e o afirmatie pe care nu o poti
        verifica - iar un filtru pe care nu-l poti verifica e unul in care n-ai cum
        sa ai incredere.
        """
        rezultat = filtreaza_dur(
            anunt(titlu="Payroll Specialist with on-call duties"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("cuvant gasit: 'on-call'", rezultat["motive_respingere"][0])
        self.assertIn("titlu", rezultat["motive_respingere"][0])

    def test_on_call_in_descriere_e_respins_cu_campul_la_vedere(self):
        """
        Etapa 2: cuvantul poate sta in DESCRIERE, nu doar in titlu.

        Pana la bucata 1B, filtrul vedea doar titlul: un "on-call" scris in corpul
        cardului ii scapa. Acum cauta si in descriere - iar motivul spune ca acolo
        l-a gasit ("in descriere"), nu in titlu. Fara asta, n-ai sti unde sa te uiti.
        """
        rezultat = filtreaza_dur(
            anunt(
                titlu="Payroll Specialist",
                descriere="Rol de payroll cu sarcini on-call in weekend.",
            ),
            CRITERII,
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("cuvant gasit: 'on-call'", rezultat["motive_respingere"][0])
        self.assertIn("descriere", rezultat["motive_respingere"][0])

    def test_ture_nu_prinde_structure(self):
        """
        Cautam cuvinte INTREGI. "structure", "future", "culture" NU sunt "ture".

        Fara regula asta, filtrul ar respinge jumatate din anunturile in engleza -
        tacut, consecvent, si cu un motiv care ar arata rezonabil in raport.
        """
        rezultat = filtreaza_dur(
            anunt(titlu="Payroll Analyst - HR structure and future planning"),
            CRITERII,
        )

        self.assertEqual(rezultat["verdict"], "trece")

    def test_ture_ca_termen_de_sine_statator_e_respins(self):
        """Perechea testului de mai sus: cuvantul real trebuie sa fie tot prins."""
        rezultat = filtreaza_dur(
            anunt(titlu="Operator payroll, se lucreaza in ture"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("'ture'", rezultat["motive_respingere"][0])

    def test_garda_prinde_si_fara_diacritice(self):
        rezultat = filtreaza_dur(anunt(titlu="Specialist payroll, garda de noapte"), CRITERII)

        self.assertEqual(rezultat["verdict"], "respins")

    def test_FALS_POZITIV_on_call_scheduling_software(self):
        """
        CAZUL DE URMARIT. Rezultatul de mai jos e RESPINS - si e un fals pozitiv.

        "on-call scheduling software" e un produs software pentru gestionarea garzilor.
        Un rol de payroll la o firma care VINDE asa ceva nu presupune ca TU faci garzi.
        Filtrul nu are cum sa stie asta: vede cuvantul si taie.

        Testul asta NU verifica un comportament corect. Verifica un comportament CUNOSCUT,
        ca sa nu se schimbe pe furis si ca sa fie vizibil cand te uiti in suita. Daca
        maine se decide altfel, testul asta pica primul si te intreaba explicit.

        Cat de mult doare: cuvantul trebuie sa apara in titlul unui anunt de payroll,
        deci cazul e rar. Iar motivul scrie cuvantul gasit, deci se vede din lista de
        respinse in cateva secunde. Alternativele - sa nu cauti "on-call" deloc, sau
        sa intrebi un model - costa fiecare mai mult decat costa greseala asta.
        """
        rezultat = filtreaza_dur(
            anunt(titlu="Payroll Consultant - on-call scheduling software"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("cuvant gasit: 'on-call'", rezultat["motive_respingere"][0])


class TestLimbi(unittest.TestCase):
    """
    Constrangerea de limba, adaugata in criteriile 1.3.

    De ce e DURA si nu calitativa: fara limba nu poti face jobul, oricat de bine s-ar
    potrivi restul. Cazul care a produs regula - un "Senior Business Partner - HR
    Development (with German)" ajuns in capul briefingului - nu era o potrivire mai
    slaba, era o imposibilitate.
    """

    def test_with_german_in_titlu_e_respins(self):
        """Cazul real din rularea de azi. Motivul spune si limba, si tiparul."""
        rezultat = filtreaza_dur(
            anunt(titlu="Senior Business Partner - HR Development (with German)"),
            CRITERII,
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("germana", rezultat["motive_respingere"][0])
        self.assertIn("with german", rezultat["motive_respingere"][0])

    def test_multilingual_e_respins(self):
        """
        "Multilingual" nu numeste nicio limba, dar cere prin definitie mai mult decat
        romana si engleza - altfel n-ar scrie-o nimeni in titlu.
        """
        rezultat = filtreaza_dur(
            anunt(titlu="Multilingual HRBP (Business Partner)"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("mai multe limbi", rezultat["motive_respingere"][0])

    def test_germany_NU_e_german(self):
        """
        TESTUL CARE PAZESTE REGULA. Cautam cuvinte INTREGI: "Germany" nu e "German".

        Fara asta, un rol remote la o firma nemteasca - exact felul de anunt pe care il
        vrem - ar fi respins fiindca in titlu scrie tara. O respingere din asta nu se
        vede niciodata: anuntul dispare, si pare ca n-a existat.
        """
        rezultat = filtreaza_dur(
            anunt(titlu="Payroll Specialist - Germany (remote)"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "trece")

    def test_limba_vorbita_nu_respinge(self):
        """
        Engleza e in `vorbite`, deci "with English" nu are voie sa respinga nimic.

        Asta e chiar rostul constructiei: lista `vorbite` conduce filtrul. Daca maine
        muti "germana" acolo, anunturile cu germana inceteaza sa mai fie respinse, fara
        sa se atinga nicio linie de cod.
        """
        rezultat = filtreaza_dur(anunt(titlu="HR Generalist with English"), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")

    def test_limba_doar_in_descriere_NU_respinge(self):
        """
        DECIZIE, nu scapare. In descriere, "germana" poate insemna "obligatoriu" sau
        "e un plus" - doua lucruri opuse, care se deosebesc citind fraza, nu dintr-un
        cuvant. Aia e judecata, deci merge la model, care o SEMNALEAZA in motivare.
        Aici, o regula determinista n-ar avea pe ce sa se sprijine.
        """
        rezultat = filtreaza_dur(
            anunt(
                titlu="HR Operations Specialist",
                descriere="Cunostintele de germana sunt un avantaj, nu o cerinta.",
            ),
            CRITERII,
        )

        self.assertEqual(rezultat["verdict"], "trece")

    def test_diacriticele_si_romana_nu_conteaza(self):
        """"Recruiter cu franceză" - acelasi lucru ca "cu franceza". Ca la cuvinte_excluse."""
        rezultat = filtreaza_dur(anunt(titlu="Recruiter cu franceză"), CRITERII)

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("franceza", rezultat["motive_respingere"][0])

    def test_aceeasi_limba_ceruta_de_doua_ori_da_un_singur_motiv(self):
        """
        "German speaker with German" cere o singura limba, de doua ori. Motivele sunt
        pentru citit, nu pentru numarat - o limba, un rand.
        """
        rezultat = filtreaza_dur(
            anunt(titlu="German speaker with German - HR Support"), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertEqual(len(rezultat["motive_respingere"]), 1)

    def test_lipsa_sectiunii_de_limbi_blocheaza(self):
        """
        O constrangere dura pe care configurarea n-o defineste NU se trateaza ca
        "totul e in regula" - la fel ca pragul salarial lipsa.
        """
        criterii = {
            "constrangeri_dure": {
                "venit_net_lunar_ron": {"prag_respingere": 5000},
                "locatie": {"baza": "Brașov", "remote_acceptat": True},
                "rol_structura": {"cuvinte_excluse": ["on-call"]},
            }
        }

        rezultat = filtreaza_dur(anunt(), criterii)

        self.assertEqual(rezultat["verdict"], "incert")
        self.assertIn("reguli de limba lipsa din criterii.yaml", rezultat["necunoscute"])


class TestVerdictGeneral(unittest.TestCase):

    def test_doua_incalcari_sunt_raportate_amandoua(self):
        """
        Nu ne oprim la prima constrangere picata.

        Daca ai vedea doar "salariu sub prag", ai putea crede ca merita renegociat.
        Vazand si "on-call", stii ca nu era nimic de salvat acolo. Raportul intreg
        costa la fel de mult de calculat si spune mult mai mult.
        """
        rezultat = filtreaza_dur(
            anunt(
                salariu_brut="4000 RON",
                titlu="Payroll Officer cu on-call",
                locatie="Cluj",
                tip_munca="onsite",
            ),
            CRITERII,
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertEqual(len(rezultat["motive_respingere"]), 3)

    def test_anuntul_curat_trece(self):
        rezultat = filtreaza_dur(anunt(), CRITERII)

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_respingere"], [])
        self.assertEqual(rezultat["necunoscute"], [])

    def test_remote_fara_salariu_trece_cu_nota(self):
        """
        SCENARIUL DIN RAPORTUL DE BUG. Un rol remote, fara salariu afisat, TREBUIE sa
        iasa "trece" - cu "salariu neafisat" scris alaturi ca nota, nu ca "incert".

        Inainte, orice necunoscut oprea "trece", iar in Romania salariul lipseste din
        aproape orice anunt - deci NICIUN anunt nu putea trece vreodata. Salariul e
        acum necunoscut NEBLOCANT: se noteaza, nu blocheaza.
        """
        rezultat = filtreaza_dur(
            anunt(tip_munca="remote", locatie="București", salariu_brut=""), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_respingere"], [])
        self.assertIn("salariu neafisat in anunt", rezultat["necunoscute"])

    def test_un_blocant_bate_un_neblocant(self):
        """
        Cand lipsesc AMANDOUA - si locatia (blocant), si salariul (neblocant) - iese
        "incert". Un singur necunoscut blocant e de ajuns ca sa opreasca "trece";
        faptul ca salariul e neblocant nu-l salveaza.
        """
        rezultat = filtreaza_dur(
            anunt(locatie="", tip_munca="nespecificat", salariu_brut=""), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "incert")
        self.assertEqual(rezultat["motive_respingere"], [])
        self.assertIn("locatie neprecizata in anunt", rezultat["necunoscute"])
        self.assertIn("salariu neafisat in anunt", rezultat["necunoscute"])

    def test_respinsul_raporteaza_si_ce_nu_stia(self):
        """
        Un anunt respins isi pastreaza lista de necunoscute.

        Daca maine descoperi ca respingerea a fost un fals pozitiv, vrei sa stii din
        prima ce ALTCEVA nu se stia despre anuntul ala - nu sa refiltrezi ca sa afli.
        """
        rezultat = filtreaza_dur(
            anunt(titlu="Payroll cu on-call", salariu_brut=""), CRITERII
        )

        self.assertEqual(rezultat["verdict"], "respins")
        self.assertIn("salariu neafisat in anunt", rezultat["necunoscute"])

    def test_lipsa_totala_de_date_nu_produce_nici_trece_nici_respins(self):
        """
        Testul care pazeste regula centrala a fisierului.

        Un anunt aproape gol nu e nici bun, nici rau: e necunoscut. Amandoua greselile
        posibile aici sunt scumpe - un "trece" fals iti umple lista de gunoi, un
        "respins" fals arunca joburi bune fara sa afli vreodata.
        """
        gol = {"id": "x", "titlu": "", "locatie": "", "tip_munca": "nespecificat"}

        rezultat = filtreaza_dur(gol, CRITERII)

        self.assertEqual(rezultat["verdict"], "incert")
        self.assertEqual(rezultat["motive_respingere"], [])
        self.assertTrue(rezultat["necunoscute"])


class TestCriteriiIncomplete(unittest.TestCase):
    """
    Ce se intampla cand criterii.yaml e stricat sau incomplet.

    Regula: o regula pe care configurarea nu o defineste NU se trateaza ca "totul e in
    ordine". O sectiune lipsa care dezactiveaza tacut o constrangere dura e exact felul
    de eroare care nu se observa luni de zile - se raporteaza ca necunoscut.
    """

    def test_criterii_goale_nu_resping_si_nu_trec(self):
        rezultat = filtreaza_dur(anunt(), {})

        self.assertEqual(rezultat["verdict"], "incert")
        self.assertEqual(rezultat["motive_respingere"], [])
        # Cate o lipsa pentru fiecare constrangere dura pe care nu o poate verifica:
        # prag salarial, oras de baza, cuvinte excluse, reguli de limba.
        self.assertEqual(len(rezultat["necunoscute"]), 4)

    def test_lipsa_pragului_salarial_se_raporteaza(self):
        criterii = {
            "constrangeri_dure": {
                "locatie": {"baza": "Brașov", "remote_acceptat": True},
                "rol_structura": {"cuvinte_excluse": ["on-call"]},
            }
        }

        rezultat = filtreaza_dur(anunt(), criterii)

        self.assertEqual(rezultat["verdict"], "incert")
        self.assertIn("prag salarial lipsa din criterii.yaml", rezultat["necunoscute"])


class TestCoada(unittest.TestCase):
    """
    Regulile care nu resping, ci pun anuntul la coada briefingului:
    biroul toata saptamana si salariul intre prag_respingere si prag_trecere.
    """

    CRITERII_COADA = {
        "constrangeri_dure": {
            **CRITERII["constrangeri_dure"],
            "venit_net_lunar_ron": {"prag_respingere": 5000, "prag_trecere": 6000},
            "locatie": {
                "baza": "Brașov",
                "remote_acceptat": True,
                "onsite_max_zile_saptamana": 2,
            },
        }
    }

    def filtreaza(self, **campuri):
        return filtreaza_dur(anunt(**campuri), self.CRITERII_COADA)

    def test_onsite_in_brasov_trece_dar_merge_la_coada(self):
        rezultat = self.filtreaza(tip_munca="onsite")

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_coada"], ["birou toata saptamana, peste 2 zile"])

    def test_hibridul_nu_merge_la_coada(self):
        # Cate zile cere un hibrid nu stim din date, deci nu-l pedepsim.
        self.assertEqual(self.filtreaza(tip_munca="hibrid")["motive_coada"], [])

    def test_remote_nu_merge_la_coada(self):
        self.assertEqual(self.filtreaza(tip_munca="remote")["motive_coada"], [])

    def test_salariu_intre_praguri_trece_dar_merge_la_coada(self):
        rezultat = self.filtreaza(tip_munca="remote", salariu_brut="5000 - 5500 RON")

        self.assertEqual(rezultat["verdict"], "trece")
        self.assertEqual(rezultat["motive_coada"], ["salariu sub 6000 RON: max 5500"])

    def test_exact_pe_prag_trecere_nu_merge_la_coada(self):
        rezultat = self.filtreaza(tip_munca="remote", salariu_brut="6000 RON")
        self.assertEqual(rezultat["motive_coada"], [])

    def test_salariu_in_euro_nu_merge_la_coada(self):
        # Necomparabil cu pragul in RON: nu respinge, deci nici nu pedepseste.
        rezultat = self.filtreaza(tip_munca="remote", salariu_brut="1400 EUR")
        self.assertEqual(rezultat["motive_coada"], [])

    def test_fara_salariu_nu_merge_la_coada(self):
        rezultat = self.filtreaza(tip_munca="remote", salariu_brut="")
        self.assertEqual(rezultat["motive_coada"], [])

    def test_ambele_motive_se_spun(self):
        rezultat = self.filtreaza(tip_munca="onsite", salariu_brut="5500 RON")
        self.assertEqual(len(rezultat["motive_coada"]), 2)

    def test_fara_regulile_de_coada_in_criterii_nu_e_nimic_la_coada(self):
        # CRITERII (cele de baza) n-au nici prag_trecere, nici onsite_max_zile_saptamana.
        rezultat = filtreaza_dur(anunt(tip_munca="onsite", salariu_brut="5500 RON"), CRITERII)
        self.assertEqual(rezultat["motive_coada"], [])


if __name__ == "__main__":
    unittest.main()
