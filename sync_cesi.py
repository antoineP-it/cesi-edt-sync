import os
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from ics import Calendar, Event

CESI_EMAIL = os.environ.get("CESI_EMAIL")
CESI_PASSWORD = os.environ.get("CESI_PASSWORD")
CODE_PERSONNE = os.environ.get("CODE_PERSONNE", "2491326")

def fetch_schedule():
    start_date = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")
    api_url = f"https://ent.cesi.fr/api/seance/all?start={start_date}&end={end_date}&codePersonne={CODE_PERSONNE}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("1. Accès direct au portail d'identification CESI...")
        page.goto("https://ent.cesi.fr/identification/", wait_until="networkidle")
        print(f"   -> URL atteinte : {page.url}")

        try:
            # Cas 1 : Page de sélection ou d'accueil CAS où il faut entrer son login/email d'abord
            email_selector = 'input[type="email"], input[name="login"], input[id="userNameInput"], input[name="UserName"], input[type="text"]'
            page.wait_for_selector(email_selector, timeout=15000)
            print(f"   -> Saisie de l'identifiant sur {page.url}...")
            page.fill(email_selector, CESI_EMAIL)

            # Vérifier si le champ mot de passe est déjà visible sur la même page (ex: ADFS sts.cesi.fr)
            pwd_selector = 'input[type="password"], input[id="passwordInput"], input[name="Password"]'
            if page.locator(pwd_selector).is_visible():
                print("   -> Champ mot de passe présent sur la même page, saisie...")
                page.fill(pwd_selector, CESI_PASSWORD)
                submit_selector = 'span[id="submitButton"], input[type="submit"], button[type="submit"]'
                page.click(submit_selector)
            else:
                # Sinon on valide d'abord l'email (redirection vers ADFS ou Microsoft)
                submit_selector = 'input[type="submit"], button[type="submit"], #idSIButton9'
                page.click(submit_selector)
                page.wait_for_load_state("networkidle")
                print(f"   -> URL après saisie de l'email : {page.url}")

                # Si le champ identifiant est pré-rempli ou redemandé sur ADFS (sts.cesi.fr)
                if page.locator('input[id="userNameInput"]').is_visible():
                    page.fill('input[id="userNameInput"]', CESI_EMAIL)

                # Attente et saisie du mot de passe
                page.wait_for_selector(pwd_selector, timeout=15000)
                print(f"   -> Saisie du mot de passe sur {page.url}...")
                page.fill(pwd_selector, CESI_PASSWORD)

                submit_pwd = 'span[id="submitButton"], input[type="submit"], button[type="submit"], #idSIButton9'
                page.click(submit_pwd)

            # Gérer l'écran éventuel "Rester connecté ?" de Microsoft
            page.wait_for_timeout(3000)
            print(f"   -> URL après validation du mot de passe : {page.url}")
            if page.locator('input[id="idSIButton9"]').is_visible():
                page.click('input[id="idSIButton9"]')

            # Attendre le retour sur ent.cesi.fr
            page.wait_for_url("**/ent.cesi.fr/**", timeout=20000)
            print(f"2. Authentification réussie ! URL finale : {page.url}")

        except Exception as e:
            print(f"Erreur détaillée pendant le login (URL actuelle = {page.url}) : {e}")
            # Affiche les champs présents sur la page pour débugger immédiatement si besoin
            inputs = page.eval_on_selector_all("input, button, a", "els => els.map(e => ({tag: e.tagName, id: e.id, name: e.name, type: e.type, text: e.innerText.slice(0,30)}))")
            print(f"Éléments détectés sur la page : {inputs}")

        print(f"3. Récupération du JSON via {api_url}...")
        response = page.request.get(api_url)
        if response.status != 200:
            raise Exception(f"Erreur API HTTP {response.status}")

        data = response.json()
        browser.close()
        return data

def generate_ics(seances):
    cal = Calendar()

    for s in seances:
        event = Event()
        event.uid = f"cesi-{s.get('code')}@ent.cesi.fr"
        event.name = s.get("title") or s.get("theme") or "Cours CESI"

        start_str = s.get("start", "")
        end_str = s.get("end", "")
        if start_str.endswith("+01") or start_str.endswith("+02"):
            start_str += ":00"
        if end_str.endswith("+01") or end_str.endswith("+02"):
            end_str += ":00"

        event.begin = start_str
        event.end = end_str

        salles_list = [salle.get("nomSalle") for salle in (s.get("salles") or []) if salle.get("nomSalle")]
        if salles_list:
            event.location = ", ".join(salles_list)

        intervenants_list = [
            f"{i.get('prenom', '')} {i.get('nom', '')}".strip()
            for i in (s.get("intervenants") or [])
        ]
        groupes_list = [
            p.get("libelleGroupe", "")
            for p in (s.get("participants") or [])
            if p.get("libelleGroupe")
        ]

        desc_parts = []
        if intervenants_list:
            desc_parts.append(f"Intervenant(s) : {', '.join(intervenants_list)}")
        if salles_list:
            desc_parts.append(f"Salle(s) : {', '.join(salles_list)}")
        if groupes_list:
            desc_parts.append(f"Groupe : {', '.join(groupes_list)}")

        event.description = "\n".join(desc_parts)
        cal.events.add(event)

    with open("edt_cesi.ics", "w", encoding="utf-8") as f:
        f.writelines(cal.serialize_iter())
    print(f"4. Fichier edt_cesi.ics généré avec succès ({len(seances)} séances) !")

if __name__ == "__main__":
    seances = fetch_schedule()
    generate_ics(seances)
