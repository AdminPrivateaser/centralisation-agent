/**
 * CentralisationAuditController
 * Controller Apex pour la page VisualForce d'audit de centralisation Joy/Privateaser.
 * Construit l'URL Railway à partir des champs de la fiche Account.
 */
public class CentralisationAuditController {

    private static final String RAILWAY_BASE_URL =
        'https://offersimulator-production-3934.up.railway.app/';

    public Account venue { get; private set; }
    public String auditUrl  { get; private set; }
    public List<String> missingFields { get; private set; }
    public Boolean hasRequiredFields { get; private set; }

    public CentralisationAuditController(ApexPages.StandardController sc) {
        // Re-query with all needed fields
        Id accountId = sc.getId();
        venue = [
            SELECT  Id,
                    Name,
                    Website,
                    Street__c,
                    City__c,
                    Postal_Code__c,
                    Country__c,
                    Principal_Offering_Widget_Short_URL__c,
                    Principal_Offering_Marketplace_URL__c,
                    Google_My_Business_URL__c,
                    MVI_number__c,
                    Linktree_URL__c,
                    Instagram_Page_URL__c,
                    Tripadvisor_Page_URL__c
            FROM Account
            WHERE Id = :accountId
            LIMIT 1
        ];

        buildAuditUrl();
    }

    private void buildAuditUrl() {
        missingFields = new List<String>();

        // ── Required fields check ────────────────────────────────────────────
        if (String.isBlank(venue.Name))    missingFields.add('Nom de la venue');
        if (String.isBlank(venue.City__c)) missingFields.add('Ville (City__c)');

        hasRequiredFields = missingFields.isEmpty();

        // ── Build address ────────────────────────────────────────────────────
        String address = '';
        if (!String.isBlank(venue.Street__c))      address += venue.Street__c + ' ';
        if (!String.isBlank(venue.Postal_Code__c)) address += venue.Postal_Code__c + ' ';
        if (!String.isBlank(venue.City__c))        address += venue.City__c;
        address = address.trim();

        // ── Construct URL params ─────────────────────────────────────────────
        Map<String, String> params = new Map<String, String>();
        params.put('venue_name',           venue.Name                                        ?? '');
        params.put('address',              address);
        params.put('segment',              '1');   // Modifier si tu as un champ Segment sur Account
        params.put('website',              venue.Website                                      ?? '');
        params.put('instagram',            venue.Instagram_Page_URL__c                       ?? '');
        params.put('linktree',             venue.Linktree_URL__c                             ?? '');
        params.put('gmb',                  venue.Google_My_Business_URL__c                   ?? '');
        params.put('joy_widget',           venue.Principal_Offering_Widget_Short_URL__c       ?? '');
        params.put('vitrine',              venue.Principal_Offering_Marketplace_URL__c        ?? '');
        params.put('mvi',                  venue.MVI_number__c                               ?? '');
        params.put('rwg_active',           'non');   // Modifier si tu as un champ RwG sur Account
        params.put('gmb_reservation_doublon', 'inconnu');
        if (!String.isBlank(venue.Tripadvisor_Page_URL__c)) {
            params.put('autres_canaux', venue.Tripadvisor_Page_URL__c);
        }

        // ── Encode and build final URL ───────────────────────────────────────
        String queryString = '';
        for (String key : params.keySet()) {
            String val = params.get(key);
            if (!String.isBlank(val)) {
                if (queryString != '') queryString += '&';
                queryString += EncodingUtil.urlEncode(key, 'UTF-8')
                             + '='
                             + EncodingUtil.urlEncode(val, 'UTF-8');
            }
        }
        auditUrl = RAILWAY_BASE_URL + '?' + queryString;
    }

    /** Action déclenchée par le bouton — ouvre l'URL dans un nouvel onglet via JS. */
    public PageReference launchAudit() {
        PageReference ref = new PageReference(auditUrl);
        ref.setRedirect(false);
        return ref;
    }
}
