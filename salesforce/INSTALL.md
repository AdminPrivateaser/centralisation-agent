# Installation — Page VisualForce Audit de Centralisation

## Étape 1 — Créer le controller Apex

1. Salesforce → Setup → Developer Console (ou Setup > Apex Classes)
2. **New** → Colle le contenu de `CentralisationAuditController.cls`
3. **Save**

## Étape 2 — Créer la page VisualForce

1. Setup → VisualForce Pages → **New**
2. Label : `Centralisation Audit`
3. Name : `CentralisationAudit`
4. Coche **"Available for Lightning Experience, Experience Builder sites, and the mobile app"**
5. Remplace le contenu par le contenu de `CentralisationAudit.page`
6. **Save**

## Étape 3 — Ajouter le bouton sur la page Account

### Option A — Bouton custom (recommandé)
1. Setup → Object Manager → Account → **Buttons, Links, and Actions** → New Button
2. Label : `🎯 Audit Centralisation`
3. Display Type : **Detail Page Button**
4. Behavior : **Display in existing window without sidebar**
5. Content Source : **VisualForce Page**
6. Page : `CentralisationAudit`
7. Save

Puis : Page Layouts → Account Layout → Buttons → glisse le bouton dans la section "Custom Buttons"

### Option B — Onglet dédié dans les Record Pages (Lightning)
1. Setup → Lightning App Builder
2. Edite la page Account Record Page
3. Ajoute un composant **VisualForce** → sélectionne `CentralisationAudit`
4. Mets-le dans un onglet "Audit Centralisation"
5. Save & Activate

## Champs à vérifier/adapter

Si un champ est absent ou mal nommé, modifie le controller Apex :
- `segment` : par défaut "1" — si tu as un champ SF, remplace `'1'` par `venue.TonChamp__c`
- `rwg_active` : par défaut "non" — idem
- `gmb_reservation_doublon` : sélectionnable sur la page VF directement
