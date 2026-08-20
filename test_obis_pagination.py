import requests

URL = "https://api.obis.org/v3/occurrence"

TAXON_ID = 159559
PAGE_SIZE = 1000

for offset in [0, 1000, 2000, 3000]:

    response = requests.get(
        URL,
        params={
            "taxonid": TAXON_ID,
            "size": PAGE_SIZE,
            "offset": offset,
        },
        timeout=60,
    )

    response.raise_for_status()

    payload = response.json()

    records = payload.get("results", [])

    print()
    print("=" * 60)
    print(f"OFFSET: {offset}")
    print(f"TOTAL reported: {payload.get('total')}")
    print(f"RECORDS returned: {len(records)}")

    if records:

        first = records[0]

        print(
            "First occurrenceID:",
            first.get("occurrenceID")
        )

        print(
            "First internal id:",
            first.get("id")
        )

        print(
            "Scientific name:",
            first.get("scientificName")
        )