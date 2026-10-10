# Monitor vrije-sectorwoningen Utrecht

Deze monitor controleert het openbare [woningaanbod van DĀK Utrecht](https://utrecht.mijndak.nl/Woningaanbod) en meldt nieuwe woningen in de tab **Vrije sector** via Telegram. Cloudflare start de GitHub Actions-monitor elke 15 minuten. De ingestelde ontvanger kan ook `/update` naar de bot sturen voor een verse telling en de actuele vrije-sectorwoningen.

## Technische haalbaarheid, gecontroleerd op 10 oktober 2026

- **Zonder inloggen:** ja. Een uitgelogde browsersessie liet 76 advertenties zien, waarvan één vrije-sectorwoning. Inloggen is alleen nodig voor persoonlijke functies en reageren.
- **Laden van advertenties:** de eerste HTML bevat alleen een JavaScript-app. Daarna haalt de pagina JSON op via `DataActionHaalUitgelogdAanbod`, een interne OutSystems-aanroep. Het is geen gedocumenteerde openbare API.
- **Categorie:** de JSON bevat `PublicatieModel`, `EenheidSoort` en `Id`. De pagina groepeerde op dat moment één `Vrije sector`-woning en twee garages in `Parkeren & Overig`. De monitor selecteert daarom `PublicatieModel == "Vrije sector"` én `EenheidSoort == "Woonruimte"`.
- **Inloggen en Playwright:** inloggen is hier niet nodig. Playwright opent de publieke pagina zodat deze zelf de actuele sessiegegevens, API-versie en CSRF-token aanlevert. Er worden geen inloggegevens opgeslagen.
- **Beperkingen:** `/robots.txt` gaf HTTP 404, dus daaruit blijkt geen expliciete crawlregel. De [disclaimer](https://utrecht.mijndak.nl/PrivacyEnDisclaimer?Tabblad=Disclaimer) stelt dat vermenigvuldiging van website-inhoud voorafgaande toestemming vergt. Ik vond op de geraadpleegde publieke pagina's geen expliciet verbod op kleinschalige persoonlijke monitoring, maar dat is geen toestemming voor grootschalig scrapen of herpubliceren. De monitor haalt de pagina één keer per kwartier op, bewaart alleen advertentie-ID's en stuurt alleen een adres, huurprijs en link naar je eigen Telegram-chat. Stop de monitor als de aanbieder bezwaar maakt of de voorwaarden wijzigen. De interne API kan zonder aankondiging veranderen.

## Werking

De eerste succesvolle run bewaart de huidige ID's als beginstatus en stuurt geen meldingen. Daarna geeft alleen een onbekend ID een melding. De ID's staan in `seen_ids.json` en worden door de GitHub-workflow teruggeschreven naar de standaardbranch. Bij een fout wordt de status niet bijgewerkt. Er wordt geen betaalde AI-API gebruikt.

## Instellen

1. Zet deze bestanden in een GitHub-repository op de standaardbranch en schakel GitHub Actions in.
2. Maak via [BotFather](https://core.telegram.org/bots/features#botfather) een Telegram-bot, start een chat met die bot en bepaal het chat-ID.
3. Voeg onder **Settings > Secrets and variables > Actions** twee repository secrets toe: `TELEGRAM_BOT_TOKEN` en `TELEGRAM_CHAT_ID`.
4. Geef de workflow toestemming om de repository-inhoud te schrijven. Een beschermde standaardbranch die rechtstreekse commits weigert, blokkeert de opslag van ID's.
5. Start de workflow eenmaal handmatig via **Actions > Vrije sector monitor > Run workflow**. Controleer in de log dat de beginstatus is opgeslagen. Stel daarna de Cloudflare Worker hieronder in voor de automatische runs.

Zolang de Telegram Secrets ontbreken, slaat de workflow het monitoren over. Zet tokens niet in bestanden, commits of GitHub-issues. Deel de botgegevens via een vertrouwd privé-kanaal.

Je kunt de bot eerst in je eigen chat testen. Stuur een uniek bericht naar de bot en start daarna handmatig **Actions > Test Telegram** met precies dat bericht als invoer. De workflow stuurt een proefbericht terug en toont het chat-ID in de log. Zolang `TELEGRAM_CHAT_ID` nog niet als Secret is ingesteld, blijft de geplande monitor inactief.

Om het ophalen van advertenties op de GitHub-runner te controleren, start **Actions > Vrije sector monitor > Run workflow** met **dry_run** aangevinkt. De log toont het aantal advertenties en vrije-sectorwoningen. Deze proefrun verstuurt niets en schrijft geen ID's weg.

Wil je het actuele overzicht in Telegram ontvangen, start dezelfde workflow handmatig met **report** aangevinkt. De monitor haalt het aanbod opnieuw op en stuurt de telling per tab, plus adres, huur, kamers, oppervlakte en link van elke vrije-sectorwoning. Een bestaande woning wordt hierdoor niet als nieuw gemeld.

## Cloudflare-planning en `/update` vanuit Telegram

Hiervoor is de kleine Cloudflare Worker in `worker/` nodig. Telegram stuurt het commando via een webhook naar de Worker. Die controleert het Telegram-webhookgeheim en het privéchat-ID, start daarna de GitHub-workflow, en die haalt het aanbod vers op. Het antwoord duurt doorgaans ongeveer een minuut, afhankelijk van de wachttijd bij GitHub. Andere chats kunnen de workflow niet starten.

1. Maak een [fine-grained GitHub-token](https://github.com/settings/personal-access-tokens/new) dat alleen toegang heeft tot deze repository en de repositorymachtiging **Contents: Read and write**. De Worker heeft dit nodig om `repository_dispatch` te versturen. Bewaar het token als Cloudflare Worker Secret `GITHUB_DISPATCH_TOKEN`.
2. Maak in je Cloudflare-dashboard onder **Workers & Pages** een Worker met de naam `utrecht-woningalert-webhook`. Vervang de voorbeeldcode door `worker/src/index.mjs` en publiceer hem. De bron staat ook klaar voor Wrangler in `worker/wrangler.toml`. Gebruik voor Wrangler bij voorkeur een beperkt API-token; de standaard OAuth-login vraagt ruimere rechten.
3. Zet op de Worker Secrets `GITHUB_DISPATCH_TOKEN`, `TELEGRAM_CHAT_ID` (dezelfde waarde als op GitHub) en `TELEGRAM_WEBHOOK_SECRET` (een willekeurig geheim van 32 of meer tekens). Zet datzelfde webhookgeheim als GitHub repository Secret `TELEGRAM_WEBHOOK_SECRET`. Kopieer de HTTPS-URL van de Worker.
4. Voeg bij de Worker onder **Settings > Trigger events > Cron triggers** de planning `7,22,37,52 * * * *` toe. Cloudflare start daarmee op minuut 7, 22, 37 en 52 van elk uur (UTC) een GitHub Actions-run zonder overzichtsbericht. Het toevoegen van de planning kan [tot 15 minuten](https://developers.cloudflare.com/workers/configuration/cron-triggers/) nodig hebben om wereldwijd actief te worden.
5. Start **Actions > Configure Telegram webhook > Run workflow** met de Worker-URL. De bot ontvangt nu `/update` via de Worker.
6. Stuur `/update` in de ingestelde privéchat. De monitorrun in GitHub Actions laat zien of het commando is ontvangen en of het actuele overzicht is verzonden.

Als de ontvanger later verandert, wijzig `TELEGRAM_CHAT_ID` zowel in GitHub Secrets als in de Cloudflare Worker Secrets. De bestaande **Test Telegram**-workflow gebruikt `getUpdates` om een nieuw chat-ID te ontdekken en werkt alleen zolang er geen webhook actief is. Cloudflare Worker Secrets en GitHub Secrets mogen nooit in de repository worden gezet.

De Cloudflare-planning loopt elke 15 minuten, maar de uitvoering en Telegram-melding kunnen door netwerk- of GitHub-wachttijd later aankomen. Als een melding via Telegram aankomt maar de daaropvolgende Git-push mislukt, kan de volgende run dezelfde woning nogmaals melden. Die twee externe diensten bieden samen geen transactiegarantie.

## Lokaal controleren

```sh
python -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m playwright install chromium
./.venv/bin/python monitor.py --dry-run
```

Gebruik op Windows `.venv\Scripts\python.exe` in plaats van `./.venv/bin/python` en `.venv\Scripts\pip.exe` in plaats van `./.venv/bin/pip`.

De proefrun verstuurt niets en wijzigt geen status. Voor een echte lokale run zijn `TELEGRAM_BOT_TOKEN` en `TELEGRAM_CHAT_ID` als omgevingsvariabelen nodig.
