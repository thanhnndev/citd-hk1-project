import json
import urllib.request
import urllib.error
import os

api_key = "AIzaSyAZfEuIiEuIu9kqNm74bQgm5GqJbJAu0Lg"
field_mask = "places.id,places.displayName,places.formattedAddress,places.shortFormattedAddress,places.location,places.types,places.primaryType,places.primaryTypeDisplayName,places.rating,places.userRatingCount,places.priceLevel,places.currentOpeningHours,places.businessStatus,places.accessibilityOptions,places.googleMapsUri,places.websiteUri"

url = "https://places.googleapis.com/v1/places:searchText"
body = json.dumps({
    "textQuery": "Có quán nào ngon ở hàm ninh",
    "languageCode": "vi",
    "includedType": "restaurant",
    "locationBias": {
        "circle": {
            "center": {
                "latitude": 10.1741,
                "longitude": 104.0537
            },
            "radius": 5000.0
        }
    }
}).encode("utf-8")

req = urllib.request.Request(
    url,
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    },
    method="POST",
)

import sys
sys.stdout.reconfigure(encoding='utf-8')
try:
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print("HTTP Error:", e.code)
    print(e.read().decode("utf-8"))
