"""Check the public Utrecht housing overview for new free-sector homes."""

import argparse
import json
import logging
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


OFFER_URL = "https://utrecht.mijndak.nl/Woningaanbod"
DETAIL_URL = "https://utrecht.mijndak.nl/HuisDetails?PublicatieId={}"
API_ACTION = "/DataActionHaalUitgelogdAanbod"
STATE_FILE = Path(__file__).with_name("seen_ids.json")
LOG = logging.getLogger("woningmonitor")


def fetch_offers():
    # Let the public page supply its own current API version and CSRF token.
    payload = None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="nl-NL")
            for attempt in range(3):
                try:
                    with page.expect_response(
                        lambda response: API_ACTION in response.url,
                        timeout=60000,
                    ) as response_info:
                        if attempt == 0:
                            page.goto(OFFER_URL, wait_until="domcontentloaded", timeout=60000)
                        else:
                            page.reload(wait_until="domcontentloaded", timeout=60000)
                except PlaywrightTimeoutError:
                    LOG.warning("Aanbod-API reageerde niet bij poging %d", attempt + 1)
                    if attempt < 2:
                        time.sleep(2)
                    continue
                response = response_info.value
                if response.status != 200:
                    raise RuntimeError(f"Aanbod-API gaf HTTP {response.status}")
                payload = response.json()
                publications = payload.get("data", {}).get("PublicatieLijst", {}).get("List")
                if publications:
                    break
                LOG.warning("Advertentielijst leeg bij poging %d; pagina opnieuw laden", attempt + 1)
                time.sleep(2)
        finally:
            browser.close()

    if payload is None:
        raise RuntimeError("Aanbod-API antwoordde niet na drie pogingen")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("Result", {}).get("IsSuccess") is not True:
        raise RuntimeError("Aanbod-API meldde geen succesvolle respons")
    publications = data.get("PublicatieLijst", {}).get("List")
    if not isinstance(publications, list) or not publications:
        raise RuntimeError("Advertentielijst ontbreekt of bleef leeg na drie pogingen")

    homes = {}
    counts = {"Aanbod": 0, "Loting": 0, "Vrije sector": 0, "Parkeren & Overig": 0}
    for publication in publications:
        model = publication.get("PublicatieModel")
        if publication.get("EenheidSoort") != "Woonruimte":
            counts["Parkeren & Overig"] += 1
        elif model == "Aanbodmodel":
            counts["Aanbod"] += 1
        elif model == "Lotingmodel":
            counts["Loting"] += 1
        elif model == "Vrije sector":
            counts["Vrije sector"] += 1
        else:
            counts["Overig"] = counts.get("Overig", 0) + 1
        if publication.get("PublicatieModel") != "Vrije sector":
            continue
        if publication.get("EenheidSoort") != "Woonruimte":
            continue
        home_id = publication.get("Id")
        address = publication.get("Adres")
        if not isinstance(home_id, str) or not home_id.isdecimal() or not isinstance(address, dict):
            raise RuntimeError("Vrije-sectoradvertentie heeft geen geldig ID of adres")
        homes[home_id] = publication
    LOG.info("Aanbod opgehaald: %d advertenties, %d vrije-sectorwoningen", len(publications), len(homes))
    return homes, counts


def load_seen_ids():
    if not STATE_FILE.exists():
        return None
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    ids = state.get("seen_ids")
    if not isinstance(ids, list) or any(not isinstance(item, str) or not item.isdecimal() for item in ids):
        raise RuntimeError("seen_ids.json heeft een ongeldig formaat")
    return set(ids)


def save_seen_ids(ids):
    temp_file = STATE_FILE.with_suffix(".json.tmp")
    temp_file.write_text(
        json.dumps({"seen_ids": sorted(ids, key=int)}, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_file.replace(STATE_FILE)


def home_lines(home):
    address = home["Adres"]
    street = " ".join(
        str(part) for part in (
            address.get("Straatnaam", ""),
            address.get("Huisnummer", ""),
            address.get("Huisletter", ""),
            address.get("HuisnummerToevoeging", ""),
        ) if part
    )
    unit = home.get("Eenheid", {})
    lines = [f"{street}, {address.get('Woonplaats', '')}", f"Huur: € {unit.get('NettoHuur', '?')} per maand"]
    details = []
    if unit.get("AantalKamers"):
        details.append(f"{unit['AantalKamers']} kamers")
    area = str(unit.get("WoonVertrekkenTotOpp", ""))
    if area and area != "0.00":
        details.append(f"{area.rstrip('0').rstrip('.') if '.' in area else area} m²")
    if details:
        lines.append(" · ".join(details))
    lines.append(DETAIL_URL.format(home["Id"]))
    return lines


def format_message(homes):
    lines = ["Nieuwe vrije-sectorwoning(en) op DĀK Utrecht:"]
    for home in homes:
        lines.extend(["", *home_lines(home)])
    message = "\n".join(lines)
    if len(message) > 4096:
        raise RuntimeError("Telegram-bericht is te lang; advertentiestatus is niet gewijzigd")
    return message


def format_status(homes, counts):
    lines = ["Actueel aanbod DĀK Utrecht:", f"Totaal: {sum(counts.values())} advertenties"]
    lines.extend(f"{category}: {number}" for category, number in counts.items())
    lines.append("")
    lines.append("Vrije-sectorwoningen:" if homes else "Er staan nu geen vrije-sectorwoningen online.")
    for home_id in sorted(homes, key=int):
        lines.extend(["", *home_lines(homes[home_id])])
    message = "\n".join(lines)
    if len(message) > 4096:
        raise RuntimeError("Statusbericht is te lang")
    return message


def send_telegram(message, token, chat_id):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": message, "disable_web_page_preview": True}).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                result = json.load(response)
            if result.get("ok") is not True:
                raise RuntimeError("Telegram weigerde het bericht")
            return
        except (HTTPError, URLError, TimeoutError) as error:
            if attempt == 2 or isinstance(error, HTTPError) and error.code in (400, 401, 403):
                # HTTPError contains the bot token in its URL. Keep it out of logs.
                raise RuntimeError(f"Telegram-verzending mislukt: {type(error).__name__}") from None
            time.sleep(2 ** attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Lees aanbod zonder melding of statuswijziging")
    parser.add_argument("--report", action="store_true", help="Stuur ook het actuele aanbod naar Telegram")
    args = parser.parse_args()
    if args.dry_run and args.report:
        parser.error("--dry-run en --report kunnen niet samen")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not args.dry_run and (not token or not chat_id):
        raise RuntimeError("GitHub Secrets TELEGRAM_BOT_TOKEN en TELEGRAM_CHAT_ID ontbreken")

    homes, counts = fetch_offers()
    seen = load_seen_ids()
    if args.dry_run:
        LOG.info("Proefrun: huidige vrije-sector-ID's: %s", ", ".join(sorted(homes, key=int)) or "geen")
        return
    if seen is None:
        save_seen_ids(set(homes))
        LOG.info("Beginstatus opgeslagen met %d bestaande woningen; geen melding verstuurd", len(homes))
    else:
        new_ids = sorted(set(homes) - seen, key=int)
        if new_ids:
            message = format_message([homes[home_id] for home_id in new_ids])
            send_telegram(message, token, chat_id)
            save_seen_ids(seen | set(new_ids))
            LOG.info("Telegram-melding verstuurd voor %d nieuwe woningen: %s", len(new_ids), ", ".join(new_ids))
        else:
            LOG.info("Geen nieuwe vrije-sectorwoningen")
    if args.report:
        send_telegram(format_status(homes, counts), token, chat_id)
        LOG.info("Actueel aanbod naar Telegram verstuurd")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        LOG.exception("Monitor mislukt; status niet bijgewerkt")
        raise SystemExit(1)
