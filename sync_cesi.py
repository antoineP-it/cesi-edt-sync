import os
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from ics import Calendar, Event

CESI_EMAIL = os.environ.get("CESI_EMAIL")
CESI_PASSWORD = os.environ.get("CESI_PASSWORD")
CODE_PERSONNE = os.environ.get("CODE_PERSONNE", "2491326")

def fetch_schedule():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("1. Accès direct au portail d'identification CESI...")
        page.goto("https://ent.cesi.fr/identification/", wait_until="networkidle")

        # Saisie de l'email sur le WAYF
        email_selector = 'input[type="email"], input[name="login"], input[id="userNameInput"], input[name="UserName"], input[type="text"]'
        page.wait_for_selector(email_selector, timeout=15000)
        page.fill(email_selector, CESI_EMAIL)
        page.click('input[type="submit"], button[type="submit"], #idSIButton9')
        page.wait_for_load_state("networkidle")

        # Saisie du mot de passe sur ADFS (sts.viacesi.fr)
        pwd_selector = 'input[type="password"], input[id="passwordInput"], input[name="Password"]'
        page.wait_for_selector(pwd_selector, timeout=15000)
        page.fill(pwd_selector, CESI_PASSWORD)
        page.click('span[id="submitButton"], input[type="submit"], button[type="submit"], #idSIButton9')

        page.wait_for_url("**/ent.cesi.fr/**", timeout=20000)
        print(f"2. Authentification réussie ! URL : {page.url}")

        # Initialiser le contexte de la page emploi du temps
        page.goto("https://ent.cesi.fr/mon-emploi-du-temps", wait_until="networkidle")

        print("3. Récupération des séances par tranches de 7 jours...")
        all_seances = {}
        base_date = datetime.now() - timedelta(days=7)

        # On récupère 24 semaines (environ 5 mois et demi) par tranches de 7 jours
        for week in range(24):
            s_date = (base_date + timedelta(days=week * 7)).strftime("%Y-%m-%d")
            e_date = (base_date + timedelta(days=(week + 1) * 7)).strftime("%Y-%m-%d")
            ts = int(time.time() * 1000)
            api_url = f"https://ent.cesi.fr/api/seance/all?start={s_date}&end={e_date}&codePersonne={CODE_PERSONNE}&_={ts}"

            response = page.request.get(
                api_url,
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": "https://ent.cesi.fr/mon-emploi-du-temps"
                }
            )

            if response.status == 200:
                items = response.json()
                for item in items:
                    all_seances[item.get("code")] = item
            else:
                print(f"   [!] Tranche {s_date} -> {e_date} : HTTP {response.status} ({response.text()[:150]})")

        browser.close()
        print(f"   -> Total récupéré : {len(all_seances)} séances uniques.")
        return list(all_seances.values())

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
