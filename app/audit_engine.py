"""Claude-powered audit engine using the centralisation playbook."""
import json
import re
from typing import Optional
from anthropic import AsyncAnthropic


PLAYBOOK_CONTEXT = """
# CENTRALISATION PLAYBOOK — SOURCE DE VÉRITÉ

## Mission
100% centralisation = aucun canal par lequel un booker peut réserver en groupe (>10 pax) sans passer par le widget Joy ou la Vitrine Événementielle Privateaser.

## Cadre d'évaluation
- Quanti : Setup min OK / KO (binaire)
- Quali : Note sur 100 basée sur critères pondérés ci-dessous

## 🌐 Site Web — Segment 1

### Quanti (setup min OK) :
- Au moins un CTA/lien Joy ou Vitrine sur le site
- Pas d'email de réservation direct ni formulaire tailored

### Quali (35 pts max) :
- CTA groupe dans le header : 8 pts
- Bloc/section dédié privatisation/groupes/événements : 10 pts
- Widget Joy embedé sur le site : 7 pts
- Aucun canal de fuite (email direct, tél non-MVI, autre outil de réservation) : 10 pts

### DON'Ts :
- Aucun "écrivez-nous un email" pour réserver
- Aucun "appelez-nous" ne redirigeant pas vers le numéro MVI
- Aucun formulaire tailored
- Aucun autre outil de réservation que Joy

## 📍 Google My Business — Segment 1

### Quanti (setup min OK) :
- Section réservations : présence du lien Vitrine Événementielle (privateaser.com/lieu/...)
- Si pas de site web : Vitrine comme website

### Quali (25 pts max) :
- Section Réservations avec lien Vitrine Événementielle uniquement (pas de doublon widget Joy) : 12 pts (8 si partiel)
- Éditorial GMB avec mots-clés groupe (privatisation, anniversaire, afterwork) : 6 pts
- Présence d'au moins un produit avec lien Vitrine Événementielle : 7 pts (bonus)

## 🔵 Reserve with Google (RwG) — Segment 1

### Quanti (setup min OK) :
- Widget Joy activé et seul système de réservation RwG

### Quali (10 pts max) :
- Widget Joy seul actif, min pax < 20 : 10 pts

### Conditions d'éligibilité :
- Au moins 1 offering bar ou restaurant
- Ouverte au moins 1 jour/semaine
- Min pax < 20 pax
- ID Google active
- RwG activé dans Supplier → External Web Presence

## 📸 Instagram — Segment 1

### Quanti (setup min OK) :
- Lien widget Joy OU Vitrine Événementielle présent (en bio ou 1ers liens Linktree)

### Quali (12 pts max — 2 critères vérifiables uniquement) :
- Lien Joy/Vitrine dans la bio ou position 1-2 Linktree : 8 pts
- Numéro MVI Joy dans la bio : 4 pts
- ~~Posts réguliers : non évaluable sans accès au compte, ignoré~~

### DON'Ts :
- Si Linktree, le lien Joy doit être dans les 2 premiers liens
- Aucun email direct
- Aucun autre outil de réservation

## Scoring global
- Note quanti : (nb canaux setup min OK / nb canaux total) × 100
- Note quali : somme des pts obtenus / somme des pts max × 100
- Note globale = Note quanti × 40% + Note quali × 60%

## Seuils couleur
- 🟢 ≥ 80 : Excellent
- 🟠 50-79 : Moyen
- 🔴 < 50 : Faible
"""


AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "channels": {
            "type": "object",
            "properties": {
                "website": {
                    "type": "object",
                    "properties": {
                        "quanti_ok": {"type": "boolean"},
                        "quanti_detail": {"type": "string"},
                        "quali_score": {"type": "number"},
                        "quali_max": {"type": "number"},
                        "criteria": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "status": {"type": "string", "enum": ["ok", "ko", "partial"]},
                                    "points": {"type": "number"},
                                    "max_points": {"type": "number"},
                                    "detail": {"type": "string"}
                                }
                            }
                        },
                        "priority_action": {"type": "string"},
                        "available": {"type": "boolean"}
                    }
                },
                "gmb": {
                    "type": "object",
                    "properties": {
                        "quanti_ok": {"type": "boolean"},
                        "quanti_detail": {"type": "string"},
                        "quali_score": {"type": "number"},
                        "quali_max": {"type": "number"},
                        "criteria": {"type": "array", "items": {"type": "object"}},
                        "priority_action": {"type": "string"},
                        "available": {"type": "boolean"}
                    }
                },
                "rwg": {
                    "type": "object",
                    "properties": {
                        "quanti_ok": {"type": "boolean"},
                        "quanti_detail": {"type": "string"},
                        "quali_score": {"type": "number"},
                        "quali_max": {"type": "number"},
                        "criteria": {"type": "array", "items": {"type": "object"}},
                        "priority_action": {"type": "string"},
                        "available": {"type": "boolean"},
                        "eligible": {"type": "boolean"}
                    }
                },
                "instagram": {
                    "type": "object",
                    "properties": {
                        "quanti_ok": {"type": "boolean"},
                        "quanti_detail": {"type": "string"},
                        "quali_score": {"type": "number"},
                        "quali_max": {"type": "number"},
                        "criteria": {"type": "array", "items": {"type": "object"}},
                        "priority_action": {"type": "string"},
                        "available": {"type": "boolean"}
                    }
                },
                "autres_canaux": {
                    "type": "object",
                    "properties": {
                        "quanti_ok": {"type": "boolean"},
                        "quanti_detail": {"type": "string"},
                        "available": {"type": "boolean"},
                        "criteria": {"type": "array", "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "status": {"type": "string", "enum": ["ok", "ko", "partial"]},
                                "detail": {"type": "string"},
                                "points": {"type": "number"},
                                "max_points": {"type": "number"}
                            }
                        }},
                        "priority_action": {"type": "string"}
                    }
                },
                "saas": {
                    "type": "object",
                    "properties": {
                        "quanti_ok": {"type": "boolean"},
                        "quanti_detail": {"type": "string"},
                        "available": {"type": "boolean"},
                        "applicable": {"type": "boolean"},
                        "reason_na": {"type": "string"},
                        "criteria": {"type": "array", "items": {"type": "object"}},
                        "priority_action": {"type": "string"},
                        "quali_score": {"type": "number"},
                        "quali_max": {"type": "number"}
                    }
                }
            }
        },
        "priority_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "priority": {"type": "integer"},
                    "channel": {"type": "string"},
                    "leak_point": {"type": "string"},
                    "action": {"type": "string"},
                    "gain_pts": {"type": "number"}
                }
            }
        },
        "scores": {
            "type": "object",
            "properties": {
                "quanti_score": {"type": "number"},
                "quanti_detail": {"type": "string"},
                "quali_score": {"type": "number"},
                "quali_detail": {"type": "string"},
                "global_score": {"type": "number"},
                "color": {"type": "string", "enum": ["green", "orange", "red"]},
                "color_emoji": {"type": "string"}
            }
        }
    }
}


def _precompute_quanti(venue_params: dict, scraped: dict) -> dict:
    """Pre-compute quanti OK/KO based on scraped data so Claude can't override."""
    mvi_norm = re.sub(r'[\s.\-+]', '', venue_params.get('mvi', '').replace('+33', '0'))

    def has_joy(data: dict) -> bool:
        return bool(
            data.get('joy_links') or data.get('joy_links_in_bio') or
            data.get('iframes_src') or data.get('joy_in_reservations')
        )

    ws = scraped.get('website', {})
    ig = scraped.get('instagram', {})
    gmb = scraped.get('gmb', {})
    lt = scraped.get('linktree', {})

    # Website: quanti OK = Joy widget/link found anywhere
    ws_quanti = has_joy(ws) if ws.get('available') else None

    # Instagram: quanti OK = Joy link in bio OR (linktree in bio AND joy in linktree top-2)
    ig_joy_in_bio = bool(ig.get('joy_links_in_bio'))
    ig_lt_in_bio = ig.get('linktree_in_bio', False)
    lt_position = lt.get('joy_link_position') if lt.get('available') else None
    ig_lt_ok = ig_lt_in_bio and lt_position is not None and lt_position <= 1  # 0-indexed
    ig_quanti = (ig_joy_in_bio or ig_lt_ok) if ig.get('available') else None

    # MVI in instagram bio
    ig_phones = ig.get('phone_numbers_normalized', [])
    ig_has_mvi = mvi_norm and any(mvi_norm in p or p in mvi_norm for p in ig_phones)

    # RwG: trust the param
    rwg_quanti = venue_params.get('rwg_active', 'non').lower() == 'oui'

    # GMB: quanti OK = Vitrine/Joy visible dans website ou joy_links
    gmb_quanti = None
    if gmb.get('available'):
        if gmb.get('source') == 'google_places_api_v2':
            # Website set to Vitrine = setup min OK
            gmb_quanti = bool(gmb.get('joy_in_website') or gmb.get('vitrine_as_website'))
        elif gmb.get('joy_links'):
            gmb_quanti = True

    return {
        'website_quanti': ws_quanti,
        'instagram_quanti': ig_quanti,
        'instagram_has_mvi': ig_has_mvi,
        'rwg_quanti': rwg_quanti,
        'gmb_quanti': gmb_quanti,
    }


async def run_audit(venue_params: dict, scraped_data: dict, progress_callback=None) -> dict:
    """Run the full audit using Claude."""
    client = AsyncAnthropic()

    quanti_facts = _precompute_quanti(venue_params, scraped_data)

    if progress_callback:
        await progress_callback("Analyse en cours par Claude...")

    prompt = f"""Tu es un expert en centralisation de réservations pour des venues (restaurants, bars, salles d'événements) pour la plateforme Joy/Privateaser.

## Informations venue
- Nom : {venue_params.get('venue_name', 'Non renseigné')}
- Segment : {venue_params.get('segment', '1')}
- Adresse : {venue_params.get('address', 'Non renseigné')}
- Widget Joy URL : {venue_params.get('joy_widget', 'Non renseigné')}
- Vitrine Événementielle URL : {venue_params.get('vitrine', 'Non renseigné')}
- Numéro MVI : {venue_params.get('mvi', 'Non renseigné')}
- RwG activé : {venue_params.get('rwg_active', 'Non renseigné')}
- GMB doublon réservations (renseigné manuellement) : {venue_params.get('gmb_reservation_doublon', 'inconnu')}
- Plateformes SaaS Individual Booking (Segment 2) : {venue_params.get('saas_platforms', 'Non renseigné')}
- Autres canaux (Tripadvisor, Fanzo…) : {venue_params.get('autres_canaux', 'Non renseigné')}

## Playbook de référence
{PLAYBOOK_CONTEXT}

## ⚠️ FAITS PRÉ-CALCULÉS — tu DOIS utiliser ces valeurs exactes pour quanti_ok, ne les modifie pas :
- Site Web quanti_ok = {quanti_facts['website_quanti']} (Joy widget/lien détecté dans le code du site)
- Instagram quanti_ok = {quanti_facts['instagram_quanti']} (Joy en bio ou Linktree pos 1-2 en bio)
- Instagram MVI présent en bio = {quanti_facts['instagram_has_mvi']} (numéro {venue_params.get('mvi','')} trouvé dans le HTML)
- RwG quanti_ok = {quanti_facts['rwg_quanti']} (confirmé via paramètre Salesforce rwg_active)
- GMB quanti_ok = {quanti_facts['gmb_quanti']} (None = non déterminable, évalue selon données disponibles)

## Données scrapées par canal

### Site Web
{json.dumps(scraped_data.get('website', {}), ensure_ascii=False, indent=2)}

### Google My Business
{json.dumps(scraped_data.get('gmb', {}), ensure_ascii=False, indent=2)}

### Instagram
{json.dumps(scraped_data.get('instagram', {}), ensure_ascii=False, indent=2)}

### Linktree (si présent)
{json.dumps(scraped_data.get('linktree', {}), ensure_ascii=False, indent=2)}

### Individual Booking SaaS (données scrapées)
{json.dumps(scraped_data.get('saas', {}), ensure_ascii=False, indent=2)}

### Autres canaux (annuaires scrapés)
{json.dumps(scraped_data.get('autres_canaux', {}), ensure_ascii=False, indent=2)}

## Règles de notation STRICTES

### Status des critères :
- `ok` = critère rempli → points COMPLETS (= max_points)
- `partial` = critère partiellement rempli → EXACTEMENT la moitié des points (arrondi au supérieur). Le post-processing Python recalcule automatiquement, inutile de le calculer toi-même.
- `ko` = critère non rempli → 0 points
- Le champ `points` = points réellement accordés. Le champ `max_points` = points max possibles.
- Le champ `detail` = OBLIGATOIRE, 1 phrase max, rédigée pour un gérant non-technique. Style : pointer le fait observable concret, pas les noms de variables.
  - Pour OK : "✓ [ce qui est bien en place]" — ex : "Widget Joy embedé dans la section Réservations."
  - Pour Partiel : "[ce qui est là] mais [ce qui manque ou pose problème]" — ex : "Vitrine Privateaser présente, mais le Widget Joy est aussi affiché en doublon."
  - Pour KO : "Point de fuite : [description du problème concret]" — ex : "Point de fuite : numéro 06 40 26 97 12 affiché dans la section Réservations, invite explicitement à appeler pour réserver."
  - Jamais de termes techniques comme `post_count`, `joy_links`, `scraping`, `paramètre`.

### Règles SITE WEB — critères quali précis :
- **"Bloc/section dédié privatisation/groupes/événements" (10 pts)** : Marque OK si `has_reservation_section=True` ET (`has_privatisation_section=True` OU un widget Joy/iframe est présent). Une section "RÉSERVATIONS" dans la nav d'un one-pager avec le widget embedé = OK complet. Ne jamais marquer Partial simplement parce que le mot "privatisation" n'apparaît pas — la présence du widget dans une section réservations suffit.
- **"Aucun canal de fuite" (10 pts)** : KO seulement si un numéro NON-MVI (différent de {venue_params.get('mvi','')}) est affiché explicitement comme moyen de réserver, OU si un email direct de réservation est présent. Cherche dans `phone_numbers_found` les numéros différents du MVI. Check aussi `phone_mentions` pour détecter les invitations à appeler.

### Règles GMB — critères quali précis :
- **"Section Réservations avec lien Vitrine Événementielle uniquement" (12 pts)** :
  - Si `gmb_reservation_doublon = "oui"` (fourni par l'utilisateur) → doublon confirmé → Partial (6/12 pts). Action : supprimer le doublon widget Joy, ne garder que le lien Vitrine.
  - Si `gmb_reservation_doublon = "non"` → OK complet (12/12 pts).
  - Si `gmb_reservation_doublon = "inconnu"` → Partial (6/12 pts) avec note "vérification manuelle recommandée".
  - Utilise aussi `has_reservation_doublon` et `joy_reservation_links` si disponibles pour confirmer.
- **"Éditorial GMB avec mots-clés groupe" (6 pts)** : évalue via `editorial_summary`. Si vide ou absent → KO.
- **"Produit avec lien Vitrine" (7 pts)** : si `joy_in_website=True` (le website GMB = Vitrine Privateaser), c'est un signal fort que la Vitrine est mise en avant. Marque OK si `joy_in_website=True`.

### Règle QUANTI (setup min) :
Le setup min est OK/KO indépendamment des canaux de fuite. Définitions strictes :
- **Site Web** : quanti_ok = True si au moins un lien Joy/Privateaser/widget existe quelque part sur le site (iframes incluses). Un téléphone non-MVI est un POINT DE FUITE quali uniquement, jamais un motif de KO quanti.
- **GMB** : quanti_ok = True si un lien Vitrine Événementielle (privateaser.com/lieu/...) est dans la section réservations.
- **RwG** : quanti_ok = True si `rwg_active` est "oui". Si les données scrappées confirment Joy comme seul partenaire (`joy_rwg_detected=True` ou `joy_in_reservations=True`), note-le explicitement. Ne demande pas de vérification manuelle si le paramètre Salesforce confirme.
- **Instagram** : quanti_ok = True si la bio contient un lien Joy/Vitrine OU si le Linktree (quand il est présent EN BIO) contient un lien Joy/Vitrine dans les 2 premiers liens.

### Règles INSTAGRAM — Logique exacte Segment 1 :
Évalue DEUX sous-critères indépendants :

**A) Lien de réservation groupe (8 pts max) :**
- Si `linktree_in_bio = False` : cherche un lien direct Joy/Vitrine dans `joy_links_in_bio`. Si présent → ok (+8). Si absent → KO (+0).
  - Action si KO : "Ajouter un lien widget Joy (ou Vitrine Événementielle) dans la bio Instagram, derrière un CTA 'réservations' / 'réserver'"
  - NE PAS suggérer d'ajouter le Linktree dans la bio — ce n'est pas la règle du playbook.
- Si `linktree_in_bio = True` : vérifie `joy_link_position` dans le Linktree. Si position 0 ou 1 (0-indexé) → ok (+8). Si >1 → KO (+0).
- NE JAMAIS évaluer la position Linktree si `linktree_in_bio = False`.

**B) Numéro MVI (4 pts max) :**
- Le MVI est `{venue_params.get('mvi', '')}`. Normalise (sans espaces) et cherche dans `phone_numbers_normalized`. Si présent → ok (+4). Si absent → KO (+0).
- Ce critère est INDÉPENDANT du lien de réservation.

**C) Activité groupe :**
- Ce critère est NON ÉVALUABLE par scraping (impossible de lire le contenu des posts sans accès au compte). NE PAS l'inclure dans les critères. Ignore complètement.

### Normalisation MVI :
MVI = `{venue_params.get('mvi', '')}`. Normalise en retirant espaces/tirets/+33 → compare avec `phone_numbers_normalized`. Si match → MVI présent.

### GMB bloqué (CAPTCHA) :
Si `captcha_blocked=True` ou `source != "google_places_api"`, note que la vérif est partielle. Utilise les données Places API si disponibles (`joy_in_reservations`, `reservations_url`, `phone`, `editorial_summary`).

### Règles INDIVIDUAL BOOKING SaaS (Segment 2 UNIQUEMENT) :
Données dans `scraped_data["saas"]`.
- Si `applicable = False` : retourner `saas: {{available:true, applicable:false, reason_na:"Segment 1 — non applicable"}}`. Mettre quali_score=0, quali_max=0, criteria=[].
- Si Segment 2 avec plateformes dans `platforms` : pour chaque plateforme :
  - Critère label : "Lien Joy intégré dans [NomSaaS]"
  - `joy_integrated = True` → status ok, +10/10 pts. Detail : "✓ Lien Joy détecté dans le formulaire."
  - `joy_integrated = False` → status ko, +0/10 pts. Detail : "Point de fuite : aucun lien Joy dans le formulaire [NomSaaS] — les groupes >15 pax ne sont pas redirigés vers Joy."
  - `available = False` → status ko, detail : "Formulaire non accessible pour vérification."
  - Action si au moins 1 KO : "Ajouter dans le formulaire [NomSaaS] : `Pour les groupes de plus de 15 personnes, cliquez ici` → lien widget Joy"
- Quanti OK = au moins 1 plateforme a joy_integrated=True.

### Règles AUTRES CANAUX (Tripadvisor, Fanzo, PagesJaunes, etc.) :
Données dans `scraped_data["autres_canaux"]["channels"]`. Segment 1 seulement (Segment 2 : non applicable).
- Pour chaque canal dans `channels` (une entrée = un annuaire) :
  - **Critère 1 — "Lien Joy/Vitrine dans le profil [Canal]"** (BONUS — pas de points) :
    - `has_joy_or_vitrine = True` → OK, label "✓ Bonus". Detail : "✓ Lien vers Joy/Privateaser présent dans le profil."
    - `has_joy_or_vitrine = False` → KO, label "À faire". Detail : "Point de fuite : profil [Canal] visible publiquement mais aucun lien vers Joy ou la Vitrine Événementielle."
  - **Critère 2 — "Numéro MVI dans le profil [Canal]"** (BONUS — pas de points, uniquement si numéro visible) :
    - `has_mvi_phone = True` → OK.
    - `has_mvi_phone = False` ET numéro visible → KO.
    - Pas de numéro visible → ne pas créer ce critère.
  - IMPORTANT : mettre `max_points = 0` et `points = 0` pour TOUS les critères de ce canal. C'est du Better/bonus uniquement, pas noté.
- Si `scraped_data["autres_canaux"]["available"] = False` : retourner `autres_canaux: {{available:false}}`.
- Quanti OK = au moins 1 canal a has_joy_or_vitrine=True. `quali_score = 0`, `quali_max = 0`.

## Ta mission
Évalue chaque canal selon le playbook et retourne un JSON structuré avec :
1. Pour chaque canal : quanti_ok (bool), quanti_detail, quali_score (pts obtenus), quali_max (pts max), criteria avec label/status/points/max_points/detail
2. Les canaux `saas` et `autres_canaux` dans `channels` si les données sont disponibles
3. Actions prioritaires triées par gain décroissant (max 5), avec leak_point précis
4. Scores globaux : globale = quanti×40% + quali×60%

Pour RwG : eligible=true si bar/restaurant. Identifie les points de fuite spécifiques.
"""

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        tools=[{
            "name": "submit_audit",
            "description": "Soumettre le résultat structuré de l'audit de centralisation",
            "input_schema": AUDIT_SCHEMA
        }],
        tool_choice={"type": "tool", "name": "submit_audit"},
        messages=[{"role": "user", "content": prompt}]
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_audit":
            audit_data = json.loads(json.dumps(block.input))
            _post_process_scores(audit_data)
            return audit_data

    raise ValueError("Claude n'a pas retourné de résultat structuré")


def _force_quanti(audit: dict, facts: dict):
    """Override Claude's quanti decisions with pre-computed Python facts."""
    channels = audit.get("channels", {})
    mapping = {
        "website": facts.get("website_quanti"),
        "instagram": facts.get("instagram_quanti"),
        "rwg": facts.get("rwg_quanti"),
        "gmb": facts.get("gmb_quanti"),
    }
    for ch_key, forced_value in mapping.items():
        if forced_value is not None and ch_key in channels:
            channels[ch_key]["quanti_ok"] = forced_value

    # Force MVI criterion in instagram
    ig = channels.get("instagram", {})
    mvi_forced = facts.get("instagram_has_mvi")
    if mvi_forced is not None and ig.get("criteria"):
        for c in ig["criteria"]:
            if "mvi" in c.get("label", "").lower() or "numéro" in c.get("label", "").lower():
                if mvi_forced:
                    c["status"] = "ok"
                    c["points"] = c.get("max_points", 4)
                else:
                    c["status"] = "ko"
                    c["points"] = 0


def _post_process_scores(audit: dict):
    """Recalculate and validate scores."""
    import math
    channels = audit.get("channels", {})
    scores = audit.get("scores", {})

    # Enforce partial = ceil(max/2) + sort criteria by max_points desc
    for ch_data in channels.values():
        if not isinstance(ch_data, dict):
            continue
        for c in ch_data.get("criteria", []):
            max_pts = c.get("max_points", 0)
            status = c.get("status", "ko")
            if status == "ok":
                c["points"] = max_pts
            elif status == "partial":
                c["points"] = math.ceil(max_pts / 2)
            else:  # ko
                c["points"] = 0
        # Sort criteria by max_points descending (highest potential first)
        if ch_data.get("criteria"):
            ch_data["criteria"].sort(key=lambda c: c.get("max_points", 0), reverse=True)
        # Recalculate channel quali_score from criteria
        criteria = ch_data.get("criteria", [])
        if criteria:
            ch_data["quali_score"] = sum(c.get("points", 0) for c in criteria)
            ch_data["quali_max"] = sum(c.get("max_points", 0) for c in criteria)
        # N/A channels: force 0/0
        if not ch_data.get("applicable", True):
            ch_data["quali_score"] = 0
            ch_data["quali_max"] = 0

    # Recalculate quanti — EXCLUDE N/A channels (applicable=False)
    active_channels = [
        c for c in channels.values()
        if isinstance(c, dict) and c.get("available", True) and c.get("applicable", True)
    ]
    quanti_ok_count = sum(1 for c in active_channels if c.get("quanti_ok", False))
    total_channels = len(active_channels)
    if total_channels > 0:
        quanti = round(quanti_ok_count / total_channels * 100)
    else:
        quanti = 0

    # Recalculate quali
    total_pts = sum(c.get("quali_score", 0) for c in active_channels)
    total_max = sum(c.get("quali_max", 0) for c in active_channels)
    quali = round(total_pts / total_max * 100) if total_max > 0 else 0

    # Global
    global_score = round(quanti * 0.4 + quali * 0.6)

    scores["quanti_score"] = quanti
    scores["quanti_detail"] = f"{quanti_ok_count}/{total_channels} canaux setup min OK"
    scores["quali_score"] = quali
    scores["quali_detail"] = f"{total_pts}/{total_max} pts pondérés"
    scores["global_score"] = global_score

    if global_score >= 80:
        scores["color"] = "green"
        scores["color_emoji"] = "🟢"
    elif global_score >= 50:
        scores["color"] = "orange"
        scores["color_emoji"] = "🟠"
    else:
        scores["color"] = "red"
        scores["color_emoji"] = "🔴"

    audit["scores"] = scores

    # Sort priority actions: Autres canaux always last, then by gain descending
    BETTER_CHANNELS = {"autres canaux", "autres_canaux", "autres canaux (tripadvisor", "tripadvisor", "fanzo", "mappy"}
    if "priority_actions" in audit:
        def action_sort_key(a):
            channel_lower = a.get("channel", "").lower()
            is_better = any(b in channel_lower for b in BETTER_CHANNELS)
            return (1 if is_better else 0, -a.get("gain_pts", 0))
        audit["priority_actions"].sort(key=action_sort_key)
        for i, action in enumerate(audit["priority_actions"][:5]):
            action["priority"] = i + 1
