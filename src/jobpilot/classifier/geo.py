"""Country-to-city mapping for location scoring.

When a country is configured as a location preference, its major tech-hub
cities are automatically included in scoring with the same weight.
"""

# Major tech-hub cities per country. Only cities commonly seen in job listings.
COUNTRY_CITIES: dict[str, list[str]] = {
    # Western Europe
    "netherlands": [
        "amsterdam", "rotterdam", "the hague", "eindhoven", "utrecht",
        "delft", "leiden", "groningen",
    ],
    "belgium": [
        "brussels", "antwerp", "ghent", "leuven",
    ],
    "luxembourg": [
        "luxembourg city",
    ],
    "france": [
        "paris", "lyon", "toulouse", "marseille", "nantes", "bordeaux",
        "lille", "strasbourg", "montpellier", "nice",
    ],
    "germany": [
        "berlin", "munich", "hamburg", "frankfurt", "cologne",
        "dusseldorf", "stuttgart", "leipzig", "dresden", "nuremberg",
        "hannover", "dortmund", "essen", "bonn",
    ],
    "austria": [
        "vienna", "graz", "linz", "salzburg", "innsbruck",
    ],
    "switzerland": [
        "zurich", "geneva", "basel", "bern", "lausanne", "lugano",
    ],

    # Nordics
    "norway": [
        "oslo", "bergen", "trondheim", "stavanger",
    ],
    "sweden": [
        "stockholm", "gothenburg", "malmo", "lund", "uppsala",
    ],
    "denmark": [
        "copenhagen", "aarhus", "odense", "aalborg",
    ],
    "finland": [
        "helsinki", "espoo", "tampere", "turku", "oulu",
    ],
    "iceland": [
        "reykjavik",
    ],

    # British Isles
    "united kingdom": [
        "london", "manchester", "edinburgh", "bristol", "cambridge",
        "oxford", "birmingham", "leeds", "glasgow", "belfast",
        "cardiff", "liverpool", "nottingham", "reading",
    ],
    "uk": [
        "london", "manchester", "edinburgh", "bristol", "cambridge",
        "oxford", "birmingham", "leeds", "glasgow", "belfast",
        "cardiff", "liverpool", "nottingham", "reading",
    ],
    "ireland": [
        "dublin", "cork", "galway", "limerick",
    ],

    # Southern Europe
    "spain": [
        "barcelona", "madrid", "valencia", "malaga", "seville",
        "bilbao", "zaragoza",
    ],
    "portugal": [
        "lisbon", "porto", "braga", "coimbra",
    ],
    "italy": [
        "milan", "rome", "turin", "bologna", "florence", "naples",
        "padua", "genoa",
    ],
    "greece": [
        "athens", "thessaloniki",
    ],
    "malta": [
        "valletta", "sliema",
    ],
    "cyprus": [
        "nicosia", "limassol", "paphos",
    ],

    # Central & Eastern Europe
    "poland": [
        "warsaw", "krakow", "wroclaw", "gdansk", "poznan", "lodz",
        "katowice", "lublin",
    ],
    "czech republic": [
        "prague", "brno", "ostrava",
    ],
    "czechia": [
        "prague", "brno", "ostrava",
    ],
    "slovakia": [
        "bratislava", "kosice",
    ],
    "hungary": [
        "budapest", "debrecen",
    ],
    "romania": [
        "bucharest", "cluj-napoca", "timisoara", "iasi", "brasov",
    ],
    "bulgaria": [
        "sofia", "plovdiv", "varna",
    ],
    "croatia": [
        "zagreb", "split", "rijeka",
    ],
    "slovenia": [
        "ljubljana", "maribor",
    ],
    "serbia": [
        "belgrade", "novi sad", "nis",
    ],

    # Baltics
    "estonia": [
        "tallinn", "tartu",
    ],
    "latvia": [
        "riga",
    ],
    "lithuania": [
        "vilnius", "kaunas",
    ],

    # Americas
    "united states": [
        "new york", "san francisco", "los angeles", "seattle", "austin",
        "boston", "chicago", "denver", "miami", "atlanta", "dallas",
        "washington dc", "portland", "san diego", "san jose",
        "raleigh", "nashville", "minneapolis", "philadelphia",
    ],
    "usa": [
        "new york", "san francisco", "los angeles", "seattle", "austin",
        "boston", "chicago", "denver", "miami", "atlanta", "dallas",
        "washington dc", "portland", "san diego", "san jose",
        "raleigh", "nashville", "minneapolis", "philadelphia",
    ],
    "canada": [
        "toronto", "vancouver", "montreal", "ottawa", "calgary",
        "edmonton", "waterloo", "quebec city", "winnipeg", "halifax",
    ],
    "brazil": [
        "sao paulo", "rio de janeiro", "belo horizonte", "curitiba",
        "porto alegre", "florianopolis", "recife", "brasilia",
    ],
    "mexico": [
        "mexico city", "guadalajara", "monterrey", "puebla",
    ],
    "argentina": [
        "buenos aires", "cordoba", "rosario",
    ],
    "colombia": [
        "bogota", "medellin", "cali", "barranquilla",
    ],
    "chile": [
        "santiago", "valparaiso",
    ],
    "uruguay": [
        "montevideo",
    ],

    # Asia-Pacific
    "japan": [
        "tokyo", "osaka", "yokohama", "nagoya", "fukuoka", "kyoto",
    ],
    "south korea": [
        "seoul", "busan", "incheon",
    ],
    "china": [
        "beijing", "shanghai", "shenzhen", "hangzhou", "guangzhou",
        "chengdu", "nanjing", "wuhan", "suzhou",
    ],
    "india": [
        "bangalore", "bengaluru", "mumbai", "hyderabad", "pune",
        "chennai", "delhi", "new delhi", "gurgaon", "noida",
        "kolkata", "ahmedabad",
    ],
    "singapore": [
        "singapore",
    ],
    "australia": [
        "sydney", "melbourne", "brisbane", "perth", "adelaide",
        "canberra",
    ],
    "new zealand": [
        "auckland", "wellington", "christchurch",
    ],
    "taiwan": [
        "taipei", "hsinchu",
    ],
    "vietnam": [
        "ho chi minh city", "hanoi", "da nang",
    ],
    "thailand": [
        "bangkok", "chiang mai",
    ],
    "indonesia": [
        "jakarta", "bandung", "surabaya",
    ],
    "malaysia": [
        "kuala lumpur", "penang", "johor bahru",
    ],
    "philippines": [
        "manila", "cebu", "makati",
    ],
    "pakistan": [
        "karachi", "lahore", "islamabad",
    ],

    # Middle East & Africa
    "united arab emirates": [
        "dubai", "abu dhabi",
    ],
    "uae": [
        "dubai", "abu dhabi",
    ],
    "israel": [
        "tel aviv", "jerusalem", "haifa", "herzliya",
    ],
    "turkey": [
        "istanbul", "ankara", "izmir",
    ],
    "saudi arabia": [
        "riyadh", "jeddah",
    ],
    "qatar": [
        "doha",
    ],
    "south africa": [
        "cape town", "johannesburg", "durban",
    ],
    "nigeria": [
        "lagos", "abuja",
    ],
    "kenya": [
        "nairobi",
    ],
    "egypt": [
        "cairo", "alexandria",
    ],
}


def expand_locations(locations: dict[str, dict]) -> dict[str, dict]:
    """Expand country entries with their related cities.

    Cities inherit the same weight and target flag as the parent country.
    Existing entries are not overwritten (explicit city config takes priority).
    """
    expanded = dict(locations)
    for name, info in locations.items():
        cities = COUNTRY_CITIES.get(name)
        if not cities:
            continue
        for city in cities:
            if city not in expanded:
                expanded[city] = dict(info)
    return expanded
