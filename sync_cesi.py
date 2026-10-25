import os
import json
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from ics import Calendar, Event

# Configuration depuis les Secrets GitHub
CESI_EMAIL = os.environ.get("CESI_EMAIL")
CESI_PASSWORD = os.environ.get("CESI_PASSWORD")
CODE_PERSONNE = os.environ.get("CODE_PERSONNE", "2491326")

def fetch_schedule():
    # Plage : de 15 jours en arrière à 180 jours en avant
    start_date = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")
    api_url = f"https://ent.cesi.fr/api/seance/all?start={start_date}&end={end_date}&codePersonne={CODE_PERSONNE}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("1. Accès à l'ENT CESI...")
        page.goto("https://ent.cesi.fr/mon-emploi-du-temps")

        # Si redirigé vers la mire Microsoft 365 / CAS CESI
        try:
            # Saisie de l'email Microsoft (@viacesi.fr)
            page.wait_for_selector('input[type="email"]', timeout=15000)
            page.fill('input[type="email"]', CESI_EMAIL)
            page.click('input[type="submit"]')

            # Saisie du mot de passe
            page.wait_for_selector('input[type="password"]', timeout=15000)
            page.fill('input[type="password"]', CESI_PASSWORD)
            page.click('input[type="submit"]')

            # Clic éventuel sur "Rester connecté ? Oui/Non"
            try:
                page.wait_for_selector('input[id="idSIButton9"]', timeout=5000)
                page.click('input[id="idSIButton9"]')
            except Exception:
                pass

            # Attendre le retour sur ent.cesi.fr
            page.wait_for_url("**/ent.cesi.fr/**", timeout=20000)
            print("2. Authentification réussie !")
        except Exception as e:
            print(f"Note lors de la connexion : {e}")

        print(f"3. Récupération du JSON via {api_url}...")
        response = page.request.get(api_url)
        if response.status != 200:
            raise Exception(f"Erreur API HTTP {response.status}: {response.text()}")

        data = response.json()
        browser.close()
        return data

def generate_ics(seances):
    cal = Calendar()

    for s in seances:
        event = Event()
        # UID unique basé sur le code de la séance pour permettre les mises à jour
        event.uid = f"cesi-{s.get('code')}@ent.cesi.fr"
        event.name = s.get("title") or s.get("theme") or "Cours CESI"

        # Normalisation du fuseau horaire (ex: +01 -> +01:00) pour le parseur ISO
        start_str = s.get("start", "")
        end_str = s.get("end", "")
        if start_str.endswith("+01") or start_str.endswith("+02"):
            start_str += ":00"
        if end_str.endswith("+01") or end_str.endswith("+02"):
            end_str += ":00"

        event.begin = start_str
        event.end = end_str

        # Salles (ex: N231 Info, OPIBUS, S037 Box)
        salles_list = [salle.get("nomSalle") for salle in (s.get("salles") or []) if salle.get("nomSalle")]
        if salles_list:
            event.location = ", ".join(salles_list)

        # Intervenants & Groupe dans la description
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
    print(f"4. Fichier edt_cesi.ics généré avec {len(seances)} séances.")

if __name__ == "__main__":
    seances = fetch_schedule()
    generate_ics(seances)
