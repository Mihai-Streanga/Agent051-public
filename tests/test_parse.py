r"""
Teste pentru parsere, pe fragmente de HTML REALE, luate din arhiva.

Rulare:
    .\.venv\Scripts\python.exe -m unittest discover -s tests

Fragmentele de mai jos sunt scurtate, dar structura si adresele sunt exact cele din
mailurile primite. De aceea testele astea au valoare: nu verifica un HTML inventat de
mine, care ar fi trecut oricum, ci exact formele care EXISTA in cutia postala.

Ca si celelalte teste: fara retea, fara baza de date, fara parola. Ruleaza in
milisecunde, oriunde. Vezi tests/test_ingestie.py pentru de ce conteaza asta.
"""

import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent051.parse import bestjobs, ejobs, linkedin
from agent051.parse.comun import EroareParser, desfa_redirectul, fara_parametri


# =============================================================
# Fragmente reale, cate unul din fiecare sablon gasit in arhiva.
# =============================================================

# eJobs 2018: link direct, cu NUMAR.
EJOBS_2018 = """
<a href="https://www.ejobs.ro/user/locuri-de-munca/1126530/?utm_source=campaign">
  Customer Service Representative Brasov</a>
<span>SC Exemplu SRL</span>
<a href="https://www.ejobs.ro/user/searchjobs?q=">Vezi toate joburile</a>
"""

# eJobs 2019: link direct, dar cu NUME in loc de numar. Sablonul asta a rupt
# prima versiune a parserului, care cerea cifre.
EJOBS_2019 = """
<a href="https://www.ejobs.ro/user/locuri-de-munca/consilier-vanzare-gestiune-piese/">
  CONSILIER VANZARE&amp;GESTIUNE PIESE</a>
<span>ASCENT HUMAN CAPITAL SRL</span>
"""

# eJobs 2024: link de urmarire; adresa reala e in base64 la coada.
# Decodat, da: https://www.ejobs.ro/user/locuri-de-munca/j/1756111?utm_source=alert...
EJOBS_2024 = """
<a href="https://cb.mta.ejobs.ro/erdr/66257e5d-5841cec8-1-0-aHR0cHM6Ly93d3cuZWpvYnMucm8vdXNlci9sb2N1cmktZGUtbXVuY2Evai8xNzU2MTExP3V0bV9zb3VyY2U9YWxlcnQ=">
  Agent Social Media (Remote - PFA/SRL)</a>
<span>Atlantic London</span>
"""

# eJobs: pagina de CAUTARE pe oras. NU e un anunt - si nu are voie sa fie luat drept
# unul. Observa ca ii lipseste "/user/" din adresa.
EJOBS_DOAR_CAUTARE = """
<a href="https://www.ejobs.ro/locuri-de-munca/brasov">Joburi in Brasov</a>
<a href="https://www.ejobs.ro/user/setari-alerte.php">Setari alerte</a>
"""

# BestJobs 2024 (romana): firma vine DUPA titlu.
BESTJOBS_2024 = """
<a href="https://news.bestjobs.eu/click/436/216/zppi/ac71/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Floc-de-munca%2Fdigital-marketing-with-dutch%3Futm_source%3Dalert">
  Digital Marketing with Dutch</a>
<a href="https://news.bestjobs.eu/click/436/216/zppi/9d6e/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Ffirme%2Fhrs-recruitment-services-srl">
  HRS STAFFING SERVICES S.R.L.</a>
"""

# BestJobs, card cu SALARIU si tag-uri sub titlu. Structura e exact cea din arhiva:
# titlu (link), firma (link), apoi textele cardului - salariu, felul muncii, oras,
# beneficiu - si un link "& altele" care inchide cardul. In arhiva, TOATE salariile
# BestJobs sunt in euro, cu forma "805 - 890 € (Estimare salariala)".
BESTJOBS_CU_SALARIU = """
<a href="https://news.bestjobs.eu/click/1/2/zppi/aa/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Floc-de-munca%2Fhr-specialist-partner">
  HR Specialist / Partner</a>
<a href="https://news.bestjobs.eu/click/1/2/zppi/bb/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Ffirme%2Fsaguaro-technology">
  SAGUARO TECHNOLOGY Inc.</a>
<span>/ 805 - 890 &euro; (Estimare salariala)</span>
<span>Job remote</span>
<span>Bonus de performan&#539;&#259;</span>
<a href="https://news.bestjobs.eu/click/1/2/zppi/cc/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Floc-de-munca%2Fhr-specialist-partner">& altele</a>
"""

# BestJobs, card FARA salariu: doar felul muncii si orasul sub titlu. Nu tot anuntul
# afiseaza salariul - atunci salariu_brut ramane gol, si nu e o eroare.
BESTJOBS_FARA_SALARIU = """
<a href="https://news.bestjobs.eu/click/1/2/zppi/aa/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Floc-de-munca%2Fhr-generalist">
  Junior HR Generalist</a>
<a href="https://news.bestjobs.eu/click/1/2/zppi/bb/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Ffirme%2Fbertschi">
  Bertschi Romania SRL</a>
<span>Job par&#539;ial remote</span>
<span>Brasov</span>
"""

# BestJobs, ULTIMUL card dintr-un mail: dupa el vine subsolul ("Updateaza-ti CV-ul
# pentru a primi..."), fara un titlu-link urmator care sa inchida cardul. Textul de
# subsol NU are voie sa alunece in descrierea ultimului anunt.
BESTJOBS_ULTIMUL_CARD_CU_FOOTER = """
<a href="https://news.bestjobs.eu/click/1/2/zppi/aa/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Floc-de-munca%2F1st-level-support">
  1st level support with English</a>
<a href="https://news.bestjobs.eu/click/1/2/zppi/bb/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Ffirme%2Fbosch">
  BOSCH SERVICE SOLUTIONS</a>
<span>Brasov</span>
<span>Updateaza-ti CV-ul pentru a primi cele mai potrivite joburi de pe piata</span>
<a href="https://news.bestjobs.eu/click/1/2/zppi/cc/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Fcont">Updateaza-ti CV-ul</a>
"""

# BestJobs, subsolul "joburi similare" in engleza: apare dupa ultimul card si scapase
# primei liste de fraze-footer. E doar zgomot de recomandare, nu descrierea jobului.
BESTJOBS_FOOTER_SIMILARE = """
<a href="https://www.bestjobs.eu/ro/loc-de-munca/payroll-specialist">Payroll Specialist</a>
<a href="https://www.bestjobs.eu/ro/firme/o-firma">O Firma SRL</a>
<span>And don't worry. Because we want to make your search easier, we've looked for a series of similar jobs that match your experience. Check them out!</span>
"""

# BestJobs, card legitim cu mai multe orase: "Brasov, Craiova, Iasi" e locatie
# adevarata, NU footer. Trebuie pastrata intreaga - e exact cazul care nu are voie sa
# cada odata cu subsolul.
BESTJOBS_MULTI_ORAS = """
<a href="https://www.bestjobs.eu/ro/loc-de-munca/recruiter">Recruiter cu germana</a>
<a href="https://www.bestjobs.eu/ro/firme/alta-firma">Alta Firma SRL</a>
<span>Job par&#539;ial remote</span>
<span>Bra&#537;ov, Craiova, Ia&#537;i</span>
<span>Bonus de performan&#539;&#259;</span>
"""

# BestJobs 2019 (engleza): alte cai (/en/job/, /en/companies/) SI firma vine INAINTE
# de titlu. Doua diferente deodata fata de sablonul nou.
BESTJOBS_2019 = """
<a href="http://news.bestjobs.eu/click/139/216/zppi/0be1/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fen%2Fcompanies%2Fdeutsche-telekom">
  Deutsche Telekom Services Europe Romania S.R.L.</a>
<a href="http://news.bestjobs.eu/click/139/216/zppi/2001/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fen%2Fjob%2Ftranslation-and-interpreting-order-support">
  Translation and Interpreting Order Support</a>
"""

# eJobs 2026: intre titlu si firma s-a strecurat o insigna ("Nou"), iar firma vine cu
# separatorul lipit de ea. Fragment real - din el au iesit 265 de anunturi cu firma "Nou".
EJOBS_CU_INSIGNA_NOU = """
<a href="https://www.ejobs.ro/user/locuri-de-munca/j/1190934?utm_source=marketing">
  Dispecer Transport</a>
<span>Nou</span>
<span>| INTERNATIONAL ALEXANDER</span>
<a href="https://www.ejobs.ro/user/locuri-de-munca/j/1190934?utm_source=marketing"></a>
"""

# eJobs: numele firmei RUPT de marcaj. eJobs pune punctele in etichete separate (probabil
# ca sa nu i le transforme in link-uri programele de mail), asa ca "S.C. HATTRICK BET
# S.R.L." ajunge la parser in zece bucati. Fragment real - din el au iesit firme numite "S".
EJOBS_FIRMA_RUPTA_DE_PUNCTE = """
<a href="https://www.ejobs.ro/user/locuri-de-munca/j/1180001?utm_source=marketing">
  Slot Tehnician (Tehnician electromecanic)</a>
<p> S<span>.</span>C<span>.</span> HATTRICK BET S<span>.</span>R<span>.</span>L<span>.</span></p>
"""

# Acelasi fel de rupere, dar cu un spatiu chiar la granita dintre bucati: " SRL" e o
# bucata separata. Daca spatiile de la margini se pierd, iese "JUMBO EC.R.SRL" - un nume
# de firma pe care nu-l scrie nimeni nicaieri, inventat de noi.
EJOBS_FIRMA_RUPTA_CU_SPATIU = """
<a href="https://www.ejobs.ro/user/locuri-de-munca/j/1180002?utm_source=marketing">
  Lucrator comercial</a>
<p> JUMBO EC<span>.</span>R<span>.</span> SRL</p>
"""

# ULTIMUL card dintr-un mail: dupa firma vine eticheta "Compania" si randul de
# dezabonare, fara niciun link care sa inchida cardul. Nu au voie sa intre in nume.
EJOBS_ULTIMUL_CARD_CU_SUBSOL = """
<a href="https://www.ejobs.ro/user/locuri-de-munca/j/1180003?utm_source=marketing">
  Consultant vanzari</a>
<p> Axen Group As S<span>.</span>R<span>.</span>L<span>.</span></p>
<p>Compania</p>
<p>Dac&#259; nu vrei s&#259; mai prime&#537;ti alerte:</p>
"""

# BestJobs 2026: TOT cardul e un singur link. Textul lui e titlul plus tot mobilierul
# paginii - firma, estimarea de salariu, adresa, indemnul de a aplica. Fragment real
# (mailul "MIND AUTOMOBILE PART ROMANIA SRL angajeaza Multilingual HRBP").
BESTJOBS_2026_CARD_INTR_UN_LINK = """
<a href="https://www.bestjobs.eu/company-profile/mind-automobile-part?utm_source=alert"></a>
<a href="https://www.bestjobs.eu/loc-de-munca/multilingual-hrbp-business-partner?utm_source=alert">
  Multilingual HRBP (Business Partner) MIND AUTOMOBILE PART ROMANIA SRL
  / Estimare pia&#539;&#259; pe pozitii similare: 1645 - 1820 &euro;
  Strada Exemplului, Bra&#537;ov, Rom&acirc;nia Evalueaz&#259; CV cu Bestie &#537;i aplic&#259;</a>
"""

# Acelasi card, in mailul ENGLEZESC: alta adresa (/en/job/), alt text de mobilier.
# Acelasi job - si trebuie sa primeasca acelasi id.
BESTJOBS_2026_CARD_IN_ENGLEZA = """
<a href="https://www.bestjobs.eu/en/job/multilingual-hrbp-business-partner?utm_source=alert">
  Multilingual HRBP (Business Partner) MIND AUTOMOBILE PART ROMANIA SRL
  / Market estimate on similar positions: 1645 - 1820 &euro;
  Strada Exemplului, Bra&#537;ov, Rom&acirc;nia Evaluate your CV with Bestie and apply</a>
"""

# Forma REALA a cardului 2026 (mailurile din 29 sept. 2026): fiecare bucata in celula ei,
# toate in acelasi <a>. Fragment redus, dupa "Economist SILURUS" si "Contabil Sef MEGA GROUP".
BESTJOBS_2026_CARD_PE_CELULE = """
<a href="https://www.bestjobs.eu/en/job/contabil-sef-957?utm_source=alert"><table><tr>
<td>Contabil Sef</td></tr><tr><td>MEGA GROUP</td></tr><tr><td>/ 1200 - 1400&euro;</td></tr>
<tr><td>Strada Lunga 10, Bra&#537;ov, Rom&acirc;nia</td></tr>
<tr><td>Evaluate your CV with Bestie and apply</td></tr></table></a>
"""

BESTJOBS_2026_CARD_PE_CELULE_ESTIMARE = """
<a href="https://www.bestjobs.eu/en/job/economist-4031?utm_source=alert"><table><tr>
<td>Economist</td></tr><tr><td>SILURUS</td></tr>
<tr><td>/ Market estimate on similar positions: 1140 - 1260 &euro;</td></tr>
<tr><td>Bra&#537;ov, Rom&acirc;nia</td></tr>
<tr><td>Evaluate your CV with Bestie and apply</td></tr></table></a>
"""

# Titlu rupt de marcaj, FARA indemnul de card: bucatile nu sunt celule, nu se desparte.
BESTJOBS_TITLU_RUPT = """
<a href="https://www.bestjobs.eu/ro/loc-de-munca/hr-specialist-9?utm_source=alert"><b>HR</b> Specialist</a>
"""

# LinkedIn "career insights" (29 sept. 2026): tot cardul in link, pe celule.
LINKEDIN_CARD_IN_LINK = """
<a href="https://www.linkedin.com/comm/jobs/view/4427014222/?trk=eml"><table><tr>
<td><img alt="Schaeffler"></td><td><table><tr>
<td>Manager Payroll Harmonization Europe (d/f/m)</td></tr>
<tr><td> Schaeffler · Bra&#351;ov </td></tr></table></td></tr></table></a>
"""

# LinkedIn 2026: firma si locatia stau pe acelasi rand, despartite de "·".
LINKEDIN_2026 = """
<a href="https://www.linkedin.com/comm/jobs/view/4407616313/?trackingId=abc123">
  HR Generalist with English</a>
<span>Accenture Romania · Bucure&#537;ti (Regim hibrid)</span>
<span>3 contacte</span>
"""

# LinkedIn 2026, exact forma din arhiva care a produs bug-ul: sub "Firma · Locatie"
# vin INSIGNE de interfata ("Recrutează activ"), nu "3 contacte". Parserul vechi lua
# insigna drept locatie si lasa orasul lipit de firma. Fragment real (DHL Supply Chain).
LINKEDIN_2026_INSIGNA = """
<a href="https://www.linkedin.com/comm/jobs/view/4409999111/?trackingId=xyz">
  Human Resources Operations Specialist</a>
<span>DHL Supply Chain · &#536;tef&#259;ne&#537;ti</span>
<span>Recruteaz&#259; activ</span>
"""

# LinkedIn 2019: mail de tip rezumat. NU contine niciun link catre un job anume,
# doar catre cautari. Din el chiar nu se poate extrage nimic.
LINKEDIN_2019_REZUMAT = """
<a href="https://www.linkedin.com/comm/jobs/search?keywords=Payroll+Specialist">
  153 de oportunitati de job</a>
<a href="https://www.linkedin.com/comm/jobs/?trk=eml">Vizualizati mai multe joburi</a>
"""


class TestEjobs(unittest.TestCase):

    def test_sablon_2018_cu_numar(self):
        anunturi = ejobs.extrage(EJOBS_2018, "mesaj-1")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["titlu"], "Customer Service Representative Brasov")
        self.assertEqual(anunturi[0]["firma"], "SC Exemplu SRL")
        self.assertEqual(
            anunturi[0]["link"], "https://www.ejobs.ro/user/locuri-de-munca/1126530"
        )

    def test_sablon_2019_cu_nume_in_loc_de_numar(self):
        """Sablonul asta a rupt prima versiune a parserului. Sa nu se mai intample."""
        anunturi = ejobs.extrage(EJOBS_2019, "mesaj-2")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["firma"], "ASCENT HUMAN CAPITAL SRL")
        self.assertIn("consilier-vanzare", anunturi[0]["link"])

    def test_sablon_2024_cu_link_de_urmarire(self):
        """Adresa reala e ascunsa in base64. Trebuie desfacuta, altfel id-ul ar fi instabil."""
        anunturi = ejobs.extrage(EJOBS_2024, "mesaj-3")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["titlu"], "Agent Social Media (Remote - PFA/SRL)")
        # Link-ul salvat e cel REAL, nu cel de urmarire.
        self.assertEqual(
            anunturi[0]["link"], "https://www.ejobs.ro/user/locuri-de-munca/j/1756111"
        )

    def test_cardul_minimal_lasa_salariu_si_descriere_goale(self):
        """
        Mailurile eJobs din arhiva sunt carduri minime: titlu + firma, atat. Nu au
        salariu si nici descriere per anunt. Campurile noi ies goale - corect, nu
        inventam ce nu e in mail.
        """
        anunturi = ejobs.extrage(EJOBS_2018, "mesaj-1")

        self.assertEqual(anunturi[0]["salariu_brut"], "")
        self.assertEqual(anunturi[0]["descriere"], "")

    def test_insigna_Nou_NU_ajunge_firma(self):
        """
        Bug-ul reparat: intre titlu si firma sta o insigna ("Nou"), iar parserul vechi
        o lua drept firma - 265 de anunturi in baza au firma "Nou". Aceeasi specie ca
        insigna "Recrutează activ" de la LinkedIn: o eticheta de interfata luata drept
        data despre job.

        Acum insigna se sare, iar separatorul lipit de firma ("| INTERNATIONAL
        ALEXANDER") se taie din cap.
        """
        anunturi = ejobs.extrage(EJOBS_CU_INSIGNA_NOU, "mesaj-insigna")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["titlu"], "Dispecer Transport")
        self.assertEqual(anunturi[0]["firma"], "INTERNATIONAL ALEXANDER")

    def test_numele_rupt_de_marcaj_se_lipeste_la_loc(self):
        """
        Bug-ul care a produs opt firme numite "S": eJobs pune punctele din numele firmei
        in etichete separate, deci numele ajunge la parser rupt in zece bucati. Un parser
        care ia prima bucata intoarce "S".
        """
        anunturi = ejobs.extrage(EJOBS_FIRMA_RUPTA_DE_PUNCTE, "mesaj-rupt")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["firma"], "S.C. HATTRICK BET S.R.L.")

    def test_spatiul_dintre_bucati_nu_se_pierde(self):
        """
        Perechea testului de mai sus, si motivul pentru care lipirea nu e banala: daca
        spatiul de la marginea unei bucati se pierde, iese "JUMBO EC.R.SRL" - adica un
        nume de firma scris de noi, care nu apare nicaieri in mail. Vezi
        elemente_din_html(pastreaza_marginile=True).
        """
        anunturi = ejobs.extrage(EJOBS_FIRMA_RUPTA_CU_SPATIU, "mesaj-spatiu")

        self.assertEqual(anunturi[0]["firma"], "JUMBO EC.R. SRL")

    def test_subsolul_nu_intra_in_numele_firmei(self):
        """
        La ultimul card nu exista un link urmator care sa-l inchida, deci eticheta
        "Compania" si randul de dezabonare ar aluneca in nume. Aceeasi problema si
        aceeasi solutie ca la _FRAZE_FOOTER din bestjobs.py.
        """
        anunturi = ejobs.extrage(EJOBS_ULTIMUL_CARD_CU_SUBSOL, "mesaj-subsol")

        self.assertEqual(anunturi[0]["firma"], "Axen Group As S.R.L.")

    def test_pagina_de_cautare_nu_e_anunt(self):
        """
        /locuri-de-munca/brasov e o lista de joburi, nu un job. Daca l-am fi luat
        drept anunt, fiecare mail ar fi produs un anunt fals numit "Joburi in Brasov".
        """
        with self.assertRaises(EroareParser):
            ejobs.extrage(EJOBS_DOAR_CAUTARE, "mesaj-4")

    def test_acelasi_numar_in_doua_forme_are_acelasi_id(self):
        """
        Acelasi anunt vine in doua tipuri de mail: o data cu "/j/<numar>", o data cu
        numele jobului inaintea numarului. Au intrat de doua ori in baza: 63 de perechi.
        Identitatea e numarul, iar link-ul ramane cel din mail.
        """
        scurt = '<a href="https://www.ejobs.ro/user/locuri-de-munca/j/1984459">Implementator</a>'
        lung = (
            '<a href="https://www.ejobs.ro/user/locuri-de-munca/'
            'implementator-software/1984459">Implementator</a>'
        )
        din_scurt = ejobs.extrage(scurt, "mesaj-scurt")[0]
        din_lung = ejobs.extrage(lung, "mesaj-lung")[0]

        self.assertEqual(din_scurt["id"], din_lung["id"])
        self.assertNotEqual(din_scurt["link"], din_lung["link"])

    def test_ambele_forme_in_acelasi_mail_dau_un_anunt(self):
        corp = (
            '<a href="https://www.ejobs.ro/user/locuri-de-munca/j/1984459">Implementator</a>'
            '<a href="https://www.ejobs.ro/user/locuri-de-munca/implementator/1984459">'
            "Implementator</a>"
        )
        self.assertEqual(len(ejobs.extrage(corp, "mesaj")), 1)
        self.assertEqual(len(ejobs.joburi_din_linkuri(corp)), 1)

    def test_identitatea_lasa_neatinsa_adresa_fara_numar(self):
        """Forma din 2019, doar cu nume: nu ghicim un numar."""
        adresa = "https://www.ejobs.ro/user/locuri-de-munca/consilier-vanzare"
        self.assertEqual(ejobs.identitatea(adresa), adresa)
        self.assertEqual(
            ejobs.identitatea("https://www.ejobs.ro/user/locuri-de-munca/1103450"),
            "https://www.ejobs.ro/user/locuri-de-munca/j/1103450",
        )


class TestBestjobs(unittest.TestCase):

    def test_sablon_nou_firma_dupa_titlu(self):
        anunturi = bestjobs.extrage(BESTJOBS_2024, "mesaj-5")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["titlu"], "Digital Marketing with Dutch")
        self.assertEqual(anunturi[0]["firma"], "HRS STAFFING SERVICES S.R.L.")
        self.assertIn("/ro/loc-de-munca/", anunturi[0]["link"])
        # Coada de urmarire (?utm_source=...) trebuie taiata: acelasi job in doua
        # mailuri vine cu utm diferit, si ar parea doua joburi.
        self.assertNotIn("utm_source", anunturi[0]["link"])

    def test_sablon_vechi_englezesc_firma_inainte_de_titlu(self):
        """Doua diferente deodata: alte cai (/en/job/) si firma INAINTEA titlului."""
        anunturi = bestjobs.extrage(BESTJOBS_2019, "mesaj-6")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["titlu"], "Translation and Interpreting Order Support")
        self.assertEqual(
            anunturi[0]["firma"], "Deutsche Telekom Services Europe Romania S.R.L."
        )

    def test_scoate_salariu_si_descriere(self):
        """
        Din acelasi HTML, parserul scoate acum si salariul (EXACT cum apare, doar fara
        "/"-ul decorativ) si descrierea (restul textelor de sub titlu). Salariul e in
        euro - asa e in toata arhiva - si il pastram ca text, fara sa-l interpretam.
        """
        anunturi = bestjobs.extrage(BESTJOBS_CU_SALARIU, "mesaj-sal")

        self.assertEqual(len(anunturi), 1)
        a = anunturi[0]
        self.assertEqual(a["titlu"], "HR Specialist / Partner")
        self.assertEqual(a["firma"], "SAGUARO TECHNOLOGY Inc.")
        self.assertEqual(a["salariu_brut"], "805 - 890 € (Estimare salariala)")
        # Descrierea aduna ce ramane de citit sub titlu - felul muncii, beneficiul.
        self.assertIn("Job remote", a["descriere"])
        self.assertIn("Bonus", a["descriere"])
        # Salariul NU se dubleaza in descriere.
        self.assertNotIn("890", a["descriere"])

    def test_card_fara_salariu_lasa_campul_gol(self):
        """
        Nu tot anuntul are salariu. Cand lipseste, salariu_brut ramane gol - nu e o
        eroare. Descrierea (felul muncii, orasul) se scoate oricum.
        """
        anunturi = bestjobs.extrage(BESTJOBS_FARA_SALARIU, "mesaj-fara")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["salariu_brut"], "")
        self.assertIn("remote", anunturi[0]["descriere"])

    def test_subsolul_nu_aluneca_in_descrierea_ultimului_card(self):
        """
        La ultimul card nu exista un titlu urmator care sa-l inchida, asa ca textul de
        subsol ("Updateaza-ti CV-ul pentru a primi...") ar aluneca in descriere. Nu are
        voie: nu e continut de anunt. Descrierea pastreaza doar orasul.
        """
        anunturi = bestjobs.extrage(BESTJOBS_ULTIMUL_CARD_CU_FOOTER, "mesaj-footer")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["descriere"], "Brasov")
        self.assertNotIn("CV-ul", anunturi[0]["descriere"])

    def test_subsolul_joburi_similare_e_prins(self):
        """
        Subsolul "don't worry... similar jobs..." e recomandare, nu descriere. Trebuie
        prins de _FRAZE_FOOTER. Aici e singurul text al cardului, deci descrierea iese
        goala - corect, mai bine gol decat plin de subsol.
        """
        anunturi = bestjobs.extrage(BESTJOBS_FOOTER_SIMILARE, "mesaj-sim")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["descriere"], "")

    def test_multi_oras_legitim_nu_e_taiat_de_footer(self):
        """
        Perechea testului de mai sus: o locatie cu mai multe orase ("Brasov, Craiova,
        Iasi") NU are voie sa cada odata cu subsolul. E descriere adevarata.
        """
        anunturi = bestjobs.extrage(BESTJOBS_MULTI_ORAS, "mesaj-multi")

        self.assertEqual(len(anunturi), 1)
        descriere = anunturi[0]["descriere"]
        self.assertIn("Job parțial remote", descriere)
        self.assertIn("Craiova", descriere)
        self.assertIn("Bonus", descriere)


class TestBestjobsSablon2026(unittest.TestCase):
    """
    Sablonul din 2026, in care tot cardul e un singur link: titlu + firma + estimare de
    salariu + adresa + indemn. Doua forme: textul turtit intr-un singur nod (primele
    fixturi - titlul ia mobilierul, firma nu se poate afla) si forma reala, pe celule
    (BESTJOBS_2026_CARD_PE_CELULE), unde fiecare bucata se citeste separat.
    """

    def test_titlul_se_opreste_inainte_de_estimarea_de_salariu(self):
        anunturi = bestjobs.extrage(BESTJOBS_2026_CARD_INTR_UN_LINK, "mesaj-2026")

        self.assertEqual(len(anunturi), 1)
        titlu = anunturi[0]["titlu"]
        self.assertNotIn("Estimare", titlu)
        self.assertNotIn("1645", titlu)
        self.assertNotIn("Bestie", titlu)
        self.assertNotIn("Strada Exemplului", titlu)
        self.assertTrue(titlu.startswith("Multilingual HRBP (Business Partner)"))

    def test_titlul_se_opreste_si_in_engleza(self):
        """Acelasi card, alt mail: "Market estimate" in loc de "Estimare piață"."""
        anunturi = bestjobs.extrage(BESTJOBS_2026_CARD_IN_ENGLEZA, "mesaj-2026-en")

        self.assertNotIn("Market estimate", anunturi[0]["titlu"])
        self.assertNotIn("Bestie", anunturi[0]["titlu"])

    def test_firma_ramane_goala_si_e_corect(self):
        """
        In forma turtita, firma e o POZA catre /company-profile/, fara niciun text. Nu se
        poate afla din mail, deci ramane goala - si asta se vede. Se completeaza din
        pagina anuntului (vezi core/descriere.py). Un camp umplut cu ce s-a nimerit ar
        fi fost mai rau: pe cel gol il vezi.
        """
        anunturi = bestjobs.extrage(BESTJOBS_2026_CARD_INTR_UN_LINK, "mesaj-2026")

        self.assertEqual(anunturi[0]["firma"], "")

    def test_acelasi_job_in_doua_limbi_are_acelasi_id(self):
        """
        MIEZUL DEDUPLICARII. Acelasi anunt, primit in mailul romanesc si in cel
        englezesc, are doua adrese - dar e un singur job. Daca id-ul s-ar calcula din
        adresa intreaga, ar intra de doua ori in baza, ca doua oportunitati. Asa a si
        intrat: 91 de perechi.

        Identitatea e slug-ul, care e acelasi in ambele limbi si e unic pe BestJobs.
        """
        din_romana = bestjobs.extrage(BESTJOBS_2026_CARD_INTR_UN_LINK, "mesaj-ro")[0]
        din_engleza = bestjobs.extrage(BESTJOBS_2026_CARD_IN_ENGLEZA, "mesaj-en")[0]

        self.assertEqual(din_romana["id"], din_engleza["id"])
        # Link-ul RAMANE cel din mail - e data bruta, adresa care chiar a fost trimisa.
        # Doar identitatea (din care iese id-ul) se aduce la forma canonica.
        self.assertNotEqual(din_romana["link"], din_engleza["link"])

    def test_identitatea_nu_inventeaza_pe_o_adresa_necunoscuta(self):
        """
        O adresa in care nu recunoastem nicio cale de job se intoarce neschimbata.
        Mai bine doua randuri decat doua joburi diferite contopite intr-unul.
        """
        adresa = "https://www.bestjobs.eu/ceva/nou/pe-care-nu-l-stim"
        self.assertEqual(bestjobs.identitatea(adresa), adresa)

    def test_cardul_pe_celule_da_titlu_firma_si_salariu(self):
        """
        Forma reala: fiecare bucata in celula ei. Lipit, iesea titlul "Contabil Sef MEGA
        GROUP" si firma goala; acum celulele se citesc separat.
        """
        anunt = bestjobs.extrage(BESTJOBS_2026_CARD_PE_CELULE, "mesaj-celule")[0]

        self.assertEqual(anunt["titlu"], "Contabil Sef")
        self.assertEqual(anunt["firma"], "MEGA GROUP")
        self.assertEqual(anunt["salariu_brut"], "1200 - 1400€")
        self.assertEqual(anunt["locatie"], "")

    def test_estimarea_platformei_nu_e_salariu(self):
        anunt = bestjobs.extrage(BESTJOBS_2026_CARD_PE_CELULE_ESTIMARE, "mesaj-est")[0]

        self.assertEqual(anunt["titlu"], "Economist")
        self.assertEqual(anunt["firma"], "SILURUS")
        self.assertEqual(anunt["salariu_brut"], "")

    def test_titlul_rupt_de_marcaj_nu_se_desparte(self):
        anunt = bestjobs.extrage(BESTJOBS_TITLU_RUPT, "mesaj-rupt")[0]

        self.assertEqual(anunt["titlu"], "HR Specialist")
        self.assertEqual(anunt["firma"], "")

    def test_titlurile_vechi_raman_neatinse(self):
        """
        Curatarea taie DOAR mobilierul cunoscut. Un titlu de dinainte de 2026, care nu
        contine nicio fraza de-asta, trebuie sa iasa exact cum a intrat - inclusiv cu
        "/"-ul din mijlocul lui ("HR Specialist / Partner").
        """
        anunturi = bestjobs.extrage(BESTJOBS_CU_SALARIU, "mesaj-vechi")

        self.assertEqual(anunturi[0]["titlu"], "HR Specialist / Partner")


class TestLinkedin(unittest.TestCase):

    def test_cardul_intreg_in_link_se_desparte(self):
        """
        Sablonul "career insights": titlul si "Firma · Oras" in celule separate, dar in
        acelasi link. Lipit, iesea titlul "... (d/f/m) Schaeffler · Braşov" si firma goala.
        """
        anunt = linkedin.extrage(LINKEDIN_CARD_IN_LINK, "mesaj-card")[0]

        self.assertEqual(anunt["titlu"], "Manager Payroll Harmonization Europe (d/f/m)")
        self.assertEqual(anunt["firma"], "Schaeffler")
        self.assertEqual(anunt["locatie"], "Braşov")

    def test_desparte_firma_de_locatie(self):
        """
        LinkedIn lipeste firma si orasul pe acelasi rand: "Accenture Romania · Bucuresti".
        Daca nu le despartim, locatia ramane goala - iar locatia e o constrangere DURA.
        Un camp gresit umplut e mai periculos decat unul gol: pe cel gol il vezi.
        """
        anunturi = linkedin.extrage(LINKEDIN_2026, "mesaj-7")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["titlu"], "HR Generalist with English")
        self.assertEqual(anunturi[0]["firma"], "Accenture Romania")
        self.assertIn("Bucure", anunturi[0]["locatie"])
        self.assertEqual(
            anunturi[0]["link"], "https://www.linkedin.com/jobs/view/4407616313"
        )

    def test_insigna_de_interfata_NU_ajunge_locatie(self):
        """
        Bug-ul reparat: sub "Firma · Locatie", LinkedIn pune insigne ("Recrutează activ"),
        nu locatia. Parserul vechi lua insigna drept locatie ("Recrutează activ") si lasa
        orasul lipit de firma ("DHL Supply Chain · Ștefănești"). O locatie gresita produce o
        respingere FALSA la filtru - exact ce s-a intamplat cu 137 de anunturi.

        Acum: firma = "DHL Supply Chain", locatie = "Ștefănești", iar insigna nu apare
        nicaieri. Locatia se ia din randul cu "·", nu din insigna de sub el.
        """
        anunturi = linkedin.extrage(LINKEDIN_2026_INSIGNA, "mesaj-insigna")

        self.assertEqual(len(anunturi), 1)
        self.assertEqual(anunturi[0]["firma"], "DHL Supply Chain")
        self.assertEqual(anunturi[0]["locatie"], "Ștefănești")
        # Insigna nu s-a strecurat in niciun camp.
        self.assertNotIn("·", anunturi[0]["firma"])
        self.assertNotIn("Recruteaz", anunturi[0]["locatie"])

    def test_mailul_rezumat_esueaza_zgomotos(self):
        """
        Sablonul vechi LinkedIn nu contine joburi individuale. Parserul trebuie sa
        RIDICE EROARE, nu sa intoarca lista goala si sa se prefaca ca a mers.
        """
        with self.assertRaises(EroareParser) as context:
            linkedin.extrage(LINKEDIN_2019_REZUMAT, "mesaj-8")

        # Eroarea poarta cu ea sursa si id-ul mesajului - altfel n-ai sti ce sa cauti.
        self.assertEqual(context.exception.sursa, "linkedin")
        self.assertEqual(context.exception.mesaj_id, "mesaj-8")


class TestReguliComune(unittest.TestCase):

    def test_html_gol_esueaza_zgomotos(self):
        """Un mesaj fara corp nu e "zero joburi". E o problema. Se raporteaza ca atare."""
        for parser in (ejobs, bestjobs, linkedin):
            with self.assertRaises(EroareParser):
                parser.extrage("", "mesaj-gol")

    def test_acelasi_anunt_are_acelasi_id_in_mesaje_diferite(self):
        """
        Miezul idempotentei. Acelasi job, trimis in doua mailuri, are acelasi link real,
        deci acelasi id - deci intra o singura data in baza. Daca id-ul ar fi calculat
        din link-ul de URMARIRE (care difera de la mail la mail), acelasi job ar intra
        de zece ori si baza ar fi plina de fantome.
        """
        primul = ejobs.extrage(EJOBS_2018, "mesaj-A")[0]
        al_doilea = ejobs.extrage(EJOBS_2018, "mesaj-B")[0]

        self.assertEqual(primul["id"], al_doilea["id"])

    def test_taierea_cozii_de_urmarire(self):
        adresa = "https://www.ejobs.ro/user/locuri-de-munca/j/123?utm_source=alert&x=1"
        self.assertEqual(
            fara_parametri(adresa), "https://www.ejobs.ro/user/locuri-de-munca/j/123"
        )

    def test_desfacerea_redirectului_bestjobs(self):
        href = (
            "https://news.bestjobs.eu/click/1/2/zppi/abc/"
            "?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Floc-de-munca%2Fceva"
        )
        self.assertEqual(
            desfa_redirectul(href), "https://www.bestjobs.eu/ro/loc-de-munca/ceva"
        )

    def test_desfacerea_redirectului_ejobs_cu_bara_in_base64(self):
        """
        Base64-ul standard poate contine "/". Cu doar ultimul segment al caii, adresa iesea
        rupta si jobul se pierdea: 28 de mailuri "Căutari salvate", 42 de joburi (30 sept.
        2026). Tot ce urmeaza dupa a patra liniuta e adresa.
        """
        tinta = "https://www.ejobs.ro/user/locuri-de-munca/specialist-payroll/1983000?utm_source=alert"
        codat = base64.b64encode(tinta.encode()).decode().rstrip("=")
        self.assertIn("/", codat)
        href = "http://cb.mta.ejobs.ro/erdr/6a96d359d6a288-58b975ebbbb7c3-1-0-" + codat

        self.assertEqual(desfa_redirectul(href), tinta)

    def test_desfacerea_redirectului_ejobs_fara_bara(self):
        tinta = "https://www.ejobs.ro/"
        href = "http://cb.mta.ejobs.ro/erdr/6a96-58b9-1-0-" + base64.b64encode(
            tinta.encode()
        ).decode()
        self.assertEqual(desfa_redirectul(href), tinta)

    def test_link_necunoscut_ramane_neschimbat(self):
        """Ce nu e un redirect cunoscut nu se atinge. Nu inventam."""
        self.assertEqual(
            desfa_redirectul("https://exemplu.ro/ceva"), "https://exemplu.ro/ceva"
        )


# Un mail cu doua joburi, al doilea legat DOAR prin poza (link fara text). Parserul sare
# peste link-urile fara text - deci pierde jobul. Exact ce trebuie sa prinda gardianul.
BESTJOBS_JOB_DOAR_PE_POZA = BESTJOBS_2024 + """
<a href="https://news.bestjobs.eu/click/436/216/zppi/ff01/?u=https%3A%2F%2Fwww.bestjobs.eu%2Fro%2Floc-de-munca%2Fpayroll-specialist-9"><img src="poza.png"></a>
"""


class TestNumaratoareaDeControl(unittest.TestCase):
    """
    joburi_din_linkuri() numara joburile din link-uri FARA filtrele parserului. Pe un
    mail citit complet, cele doua cifre sunt egale; cand parserul pierde un job, nu.
    """

    def test_pe_mailurile_reale_numaratoarea_e_egala_cu_parserul(self):
        cazuri = [
            (ejobs, EJOBS_2018), (ejobs, EJOBS_2019), (ejobs, EJOBS_2024),
            (ejobs, EJOBS_CU_INSIGNA_NOU),
            (bestjobs, BESTJOBS_2024), (bestjobs, BESTJOBS_CU_SALARIU),
            (bestjobs, BESTJOBS_2019), (bestjobs, BESTJOBS_2026_CARD_INTR_UN_LINK),
            (linkedin, LINKEDIN_2026), (linkedin, LINKEDIN_2026_INSIGNA),
        ]
        for parser, html in cazuri:
            with self.subTest(parser=parser.__name__, inceput=html.strip()[:40]):
                self.assertEqual(
                    len(parser.joburi_din_linkuri(html)), len(parser.extrage(html))
                )

    def test_jobul_legat_doar_prin_poza_e_numarat_desi_parserul_il_pierde(self):
        self.assertEqual(len(bestjobs.extrage(BESTJOBS_JOB_DOAR_PE_POZA)), 1)
        self.assertEqual(len(bestjobs.joburi_din_linkuri(BESTJOBS_JOB_DOAR_PE_POZA)), 2)

    def test_pagina_de_cautare_nu_se_numara_ca_job(self):
        self.assertEqual(ejobs.joburi_din_linkuri(EJOBS_DOAR_CAUTARE), set())


class TestGardianulInExtragere(unittest.TestCase):
    """
    Adaptorul de extragere, cu baza inlocuita de functii inventate: mailul cu jobul
    pierdut trebuie sa iasa in `mesaje_incomplete`, cel intreg nu.
    """

    def _ruleaza(self, mesaje):
        from agent051.adapters import extragere

        inlocuiri = {
            "initializeaza_db": lambda: None,
            "mesaje_de_procesat": lambda: mesaje,
            "salveaza_anunt": lambda **campuri: True,
            "acoperire_extractie": lambda: {},
        }
        originale = {nume: getattr(extragere, nume) for nume in inlocuiri}
        for nume, functie in inlocuiri.items():
            setattr(extragere, nume, functie)
        try:
            return extragere.ruleaza_extragerea()
        finally:
            for nume, functie in originale.items():
                setattr(extragere, nume, functie)

    def _mesaj(self, id_mesaj, corp_html):
        return {
            "id": id_mesaj,
            "sursa": "bestjobs",
            "subiect": "Joburi noi pentru tine",
            "corp_html": corp_html,
            "data_primire": "2026-09-29T10:00:00+00:00",
        }

    def test_mailul_cu_job_pierdut_iese_incomplet(self):
        raport = self._ruleaza([
            self._mesaj("intreg", BESTJOBS_2024),
            self._mesaj("cu-pierdere", BESTJOBS_JOB_DOAR_PE_POZA),
        ])

        self.assertEqual(raport["mesaje_incomplete"], 1)
        self.assertEqual(raport["incomplete"][0]["anunturi_extrase"], 1)
        self.assertEqual(raport["incomplete"][0]["joburi_in_linkuri"], 2)

    def test_mailurile_intregi_dau_zero(self):
        raport = self._ruleaza([self._mesaj("intreg", BESTJOBS_2024)])

        self.assertEqual(raport["mesaje_incomplete"], 0)
        self.assertEqual(raport["incomplete"], [])


if __name__ == "__main__":
    unittest.main()
