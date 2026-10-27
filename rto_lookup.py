"""
rto_lookup.py - Indian Vehicle Registration Format Parser and RTO Authority Lookup Module.

Provides safe, deterministic, read-only lookup of Indian state and RTO authorities
from vehicle registration numbers when a vehicle record is missing from the local database.
"""

import re
from typing import Dict, Any, Optional, Tuple, List

# Complete dictionary of all 36 Indian States and Union Territories (plus legacy codes)
INDIAN_STATES: Dict[str, str] = {
    "AN": "Andaman and Nicobar Islands",
    "AP": "Andhra Pradesh",
    "AR": "Arunachal Pradesh",
    "AS": "Assam",
    "BR": "Bihar",
    "CG": "Chhattisgarh",
    "CH": "Chandigarh",
    "DD": "Daman and Diu",
    "DL": "Delhi",
    "DN": "Dadra and Nagar Haveli",
    "GA": "Goa",
    "GJ": "Gujarat",
    "HP": "Himachal Pradesh",
    "HR": "Haryana",
    "JH": "Jharkhand",
    "JK": "Jammu and Kashmir",
    "KA": "Karnataka",
    "KL": "Kerala",
    "LA": "Ladakh",
    "LD": "Lakshadweep",
    "MH": "Maharashtra",
    "ML": "Meghalaya",
    "MN": "Manipur",
    "MP": "Madhya Pradesh",
    "MZ": "Mizoram",
    "NL": "Nagaland",
    "OD": "Odisha",
    "OR": "Odisha",           # Older abbreviation
    "PB": "Punjab",
    "PY": "Puducherry",
    "RJ": "Rajasthan",
    "SK": "Sikkim",
    "TN": "Tamil Nadu",
    "TR": "Tripura",
    "TS": "Telangana",
    "UA": "Uttarakhand",      # Older abbreviation
    "UK": "Uttarakhand",
    "UP": "Uttar Pradesh",
    "WB": "West Bengal",
}

# Verified Indian Registering Authorities (RTO / DTO / RTA) Mapping
RTO_AUTHORITIES: Dict[str, str] = {
    # ----------------------------------------------------
    # MAHARASHTRA (MH)
    # ----------------------------------------------------
    "MH01": "Mumbai South (Tardeo)",
    "MH02": "Mumbai West (Andheri)",
    "MH03": "Mumbai East (Wadala)",
    "MH04": "Thane",
    "MH05": "Kalyan",
    "MH06": "Raigad (Pen)",
    "MH07": "Sindhudurg",
    "MH08": "Ratnagiri",
    "MH09": "Kolhapur",
    "MH10": "Sangli",
    "MH11": "Satara",
    "MH12": "Pune",
    "MH13": "Solapur",
    "MH14": "Pimpri-Chinchwad",
    "MH15": "Nashik",
    "MH16": "Ahmednagar",
    "MH17": "Shrirampur",
    "MH18": "Dhule",
    "MH19": "Jalgaon",
    "MH20": "Aurangabad (Chhatrapati Sambhajinagar)",
    "MH21": "Jalna",
    "MH22": "Parbhani",
    "MH23": "Beed",
    "MH24": "Latur",
    "MH25": "Osmanabad (Dharashiv)",
    "MH26": "Nanded",
    "MH27": "Amravati",
    "MH28": "Buldhana",
    "MH29": "Yavatmal",
    "MH30": "Akola",
    "MH31": "Nagpur Urban",
    "MH32": "Wardha",
    "MH33": "Gadchiroli",
    "MH34": "Chandrapur",
    "MH35": "Gondia",
    "MH36": "Bhandara",
    "MH37": "Washim",
    "MH38": "Hingoli",
    "MH39": "Nandurbar",
    "MH40": "Nagpur Rural",
    "MH41": "Malegaon",
    "MH42": "Baramati",
    "MH43": "Navi Mumbai (Vashi)",
    "MH44": "Ambejogai",
    "MH45": "Akluj",
    "MH46": "Panvel",
    "MH47": "Mumbai North (Borivali)",
    "MH48": "Vasai-Virar",
    "MH49": "Nagpur East",
    "MH50": "Karad",

    # ----------------------------------------------------
    # DELHI (DL)
    # ----------------------------------------------------
    "DL01": "Delhi North (Mall Road)",
    "DL02": "Delhi New (Tilak Marg)",
    "DL03": "Delhi South (Sheikh Sarai)",
    "DL04": "Delhi West (Janakpuri)",
    "DL05": "Delhi North East (Loni Road)",
    "DL06": "Delhi Central (Sarai Kale Khan)",
    "DL07": "Delhi East (Mayur Vihar)",
    "DL08": "Delhi North West (Wazirpur)",
    "DL09": "Delhi South West (Palam / Janakpuri)",
    "DL10": "Delhi West II (Raja Garden)",
    "DL11": "Delhi North West II (Rohini)",
    "DL12": "Delhi South West II (Vasant Vihar)",
    "DL13": "Delhi East II (Surajmal Vihar)",
    "DL14": "Delhi South West III (Dwarka)",
    # Historical Delhi vehicle series mapping
    "DL1C": "Delhi North (Mall Road - Car)",
    "DL2C": "Delhi New (Tilak Marg - Car)",
    "DL3C": "Delhi South (Sheikh Sarai - Car)",
    "DL4C": "Delhi West (Janakpuri - Car)",
    "DL5C": "Delhi North East (Loni Road - Car)",
    "DL6C": "Delhi Central (Sarai Kale Khan - Car)",
    "DL7C": "Delhi East (Mayur Vihar - Car)",
    "DL8C": "Delhi North West (Wazirpur - Car)",
    "DL9C": "Delhi South West (Palam - Car)",
    "DL10C": "Delhi West II (Raja Garden - Car)",
    "DL11C": "Delhi North West II (Rohini - Car)",
    "DL12C": "Delhi South West II (Vasant Vihar - Car)",
    "DL13C": "Delhi East II (Surajmal Vihar - Car)",

    # ----------------------------------------------------
    # GUJARAT (GJ)
    # ----------------------------------------------------
    "GJ01": "Ahmedabad",
    "GJ02": "Mehsana",
    "GJ03": "Rajkot",
    "GJ04": "Bhavnagar",
    "GJ05": "Surat",
    "GJ06": "Vadodara",
    "GJ07": "Nadiad (Kheda)",
    "GJ08": "Palanpur (Banaskantha)",
    "GJ09": "Himmatnagar (Sabarkantha)",
    "GJ10": "Jamnagar",
    "GJ11": "Junagadh",
    "GJ12": "Bhuj (Kutch)",
    "GJ13": "Surendranagar",
    "GJ14": "Amreli",
    "GJ15": "Valsad",
    "GJ16": "Bharuch",
    "GJ17": "Godhra (Panchmahal)",
    "GJ18": "Gandhinagar",
    "GJ19": "Bardoli",
    "GJ20": "Dahod",
    "GJ21": "Navsari",
    "GJ22": "Rajpipla (Narmada)",
    "GJ23": "Anand",
    "GJ24": "Patan",
    "GJ25": "Porbandar",
    "GJ26": "Vyara (Tapi)",
    "GJ27": "Ahmedabad East (Vastral)",
    "GJ28": "Surat West (Pal)",
    "GJ29": "Vadodara Rural",
    "GJ30": "Dang (Ahwa)",
    "GJ31": "Modasa (Arvalli)",
    "GJ32": "Veraval (Gir Somnath)",
    "GJ33": "Botad",
    "GJ34": "Chhota Udaipur",
    "GJ35": "Lunawada (Mahisagar)",
    "GJ36": "Morbi",
    "GJ37": "Khambhalia (Devbhoomi Dwarka)",
    "GJ38": "Bavla (Ahmedabad Rural)",

    # ----------------------------------------------------
    # KARNATAKA (KA)
    # ----------------------------------------------------
    "KA01": "Bangalore Central (Koramangala)",
    "KA02": "Bangalore West (Rajajinagar)",
    "KA03": "Bangalore East (Indiranagar)",
    "KA04": "Bangalore North (Yeshwanthpur)",
    "KA05": "Bangalore South (Jayanagar)",
    "KA06": "Tumkur",
    "KA07": "Kolar",
    "KA08": "KGF",
    "KA09": "Mysore West",
    "KA10": "Chamarajanagar",
    "KA11": "Mandya",
    "KA12": "Madikeri (Kodagu)",
    "KA13": "Hassan",
    "KA14": "Shimoga",
    "KA15": "Sagar",
    "KA16": "Chitradurga",
    "KA17": "Davanagere",
    "KA18": "Chikmagalur",
    "KA19": "Mangalore",
    "KA20": "Udupi",
    "KA21": "Puttur",
    "KA22": "Belgaum",
    "KA23": "Chikkodi",
    "KA24": "Bailhongal",
    "KA25": "Dharwad",
    "KA26": "Gadag",
    "KA27": "Haveri",
    "KA28": "Bijapur (Vijayapura)",
    "KA29": "Bagalkot",
    "KA30": "Karwar",
    "KA31": "Sirsi",
    "KA32": "Gulbarga (Kalaburagi)",
    "KA33": "Yadgir",
    "KA34": "Bellary",
    "KA35": "Hospet",
    "KA36": "Raichur",
    "KA37": "Koppal",
    "KA38": "Bidar",
    "KA39": "Bhalki",
    "KA40": "Chikkaballapur",
    "KA41": "Bangalore West (Kengeri)",
    "KA42": "Ramanagara",
    "KA43": "Devanahalli (Bangalore Rural)",
    "KA44": "Tiptur",
    "KA45": "Hunsur",
    "KA46": "Sakleshpur",
    "KA47": "Honnavar",
    "KA48": "Jamkhandi",
    "KA49": "Gokak",
    "KA50": "Bangalore North (Yelahanka)",
    "KA51": "Bangalore South (Electronic City)",
    "KA52": "Nelamangala",
    "KA53": "Bangalore East (K.R. Puram)",
    "KA54": "Nagamangala",
    "KA55": "Mysore East",
    "KA56": "Basavakalyan",
    "KA57": "Bangalore Central (Shantinagar)",
    "KA58": "Banashankari",
    "KA59": "Chandapura",
    "KA60": "R.T. Nagar",
    "KA61": "Marathahalli",
    "KA63": "Dandeli",
    "KA64": "Madhugiri",
    "KA65": "Sedam",
    "KA66": "Tarikere",

    # ----------------------------------------------------
    # TAMIL NADU (TN)
    # ----------------------------------------------------
    "TN01": "Chennai Central (Ayanavaram)",
    "TN02": "Chennai North (Anna Nagar)",
    "TN03": "Chennai North East (Tondiarpet)",
    "TN04": "Chennai East (Pulianthope)",
    "TN05": "Chennai North (Kolathur)",
    "TN06": "Chennai South East (Mandavelli)",
    "TN07": "Chennai South (Thiruvanmiyur)",
    "TN09": "Chennai West (K.K. Nagar)",
    "TN10": "Chennai South West (Virugambakkam)",
    "TN11": "Tambaram",
    "TN12": "Poonamallee",
    "TN13": "Ambattur",
    "TN14": "Sholinganallur",
    "TN15": "Ulundurpet",
    "TN16": "Tindivanam",
    "TN18": "Red Hills",
    "TN19": "Chengalpattu",
    "TN20": "Tiruvallur",
    "TN21": "Kanchipuram",
    "TN22": "Meenambakkam",
    "TN23": "Vellore",
    "TN24": "Krishnagiri",
    "TN25": "Tiruvannamalai",
    "TN27": "Salem",
    "TN28": "Namakkal",
    "TN29": "Dharmapuri",
    "TN30": "Salem West",
    "TN31": "Cuddalore",
    "TN32": "Villupuram",
    "TN33": "Erode",
    "TN34": "Tiruchengode",
    "TN36": "Gobichettipalayam",
    "TN37": "Coimbatore South",
    "TN38": "Coimbatore North",
    "TN39": "Tirupur North",
    "TN40": "Mettupalayam",
    "TN41": "Pollachi",
    "TN42": "Tirupur South",
    "TN43": "Ooty (Nilgiris)",
    "TN45": "Tiruchirappalli West",
    "TN46": "Perambalur",
    "TN47": "Karur",
    "TN48": "Srirangam",
    "TN49": "Thanjavur",
    "TN50": "Tiruvarur",
    "TN51": "Nagapattinam",
    "TN52": "Sankari",
    "TN54": "Salem East",
    "TN55": "Pudukkottai",
    "TN56": "Perundurai",
    "TN57": "Dindigul",
    "TN58": "Madurai South",
    "TN59": "Madurai North",
    "TN60": "Theni",
    "TN61": "Ariyalur",
    "TN63": "Sivagangai",
    "TN64": "Madurai Central",
    "TN65": "Ramanathapuram",
    "TN66": "Coimbatore Central",
    "TN67": "Virudhunagar",
    "TN68": "Kumbakonam",
    "TN69": "Thoothukudi",
    "TN70": "Tirunelveli",
    "TN72": "Tirunelveli Town",
    "TN73": "Ranipet",
    "TN74": "Nagercoil",
    "TN75": "Marthandam",
    "TN76": "Tenkasi",
    "TN77": "Attur",
    "TN78": "Dharapuram",
    "TN79": "Sankarankovil",
    "TN81": "Tiruchirappalli East",
    "TN82": "Mayiladuthurai",
    "TN83": "Vaniyambadi",
    "TN84": "Srivilliputhur",
    "TN85": "Kundrathur",
    "TN87": "Sriperumbudur",
    "TN88": "Namakkal South",
    "TN90": "Hosur",
    "TN91": "Neyveli",
    "TN92": "Tiruchendur",
    "TN93": "Mettur",
    "TN94": "Palani",
    "TN95": "Sivakasi",
    "TN96": "Kovilpatti",
    "TN99": "Coimbatore West",

    # ----------------------------------------------------
    # UTTAR PRADESH (UP)
    # ----------------------------------------------------
    "UP11": "Saharanpur",
    "UP12": "Muzaffarnagar",
    "UP13": "Bulandshahr",
    "UP14": "Ghaziabad",
    "UP15": "Meerut",
    "UP16": "Gautam Buddha Nagar (Noida)",
    "UP17": "Baghpat",
    "UP19": "Shamli",
    "UP20": "Bijnor",
    "UP21": "Moradabad",
    "UP22": "Rampur",
    "UP23": "Sambhal",
    "UP24": "Badaun",
    "UP25": "Bareilly",
    "UP26": "Pilibhit",
    "UP27": "Shahjahanpur",
    "UP30": "Hardoi",
    "UP31": "Lakhimpur Kheri",
    "UP32": "Lucknow",
    "UP33": "Raebareli",
    "UP34": "Sitapur",
    "UP35": "Unnao",
    "UP36": "Amethi",
    "UP37": "Hapur",
    "UP40": "Bahraich",
    "UP41": "Barabanki",
    "UP42": "Ayodhya (Faizabad)",
    "UP43": "Gonda",
    "UP44": "Sultanpur",
    "UP45": "Shravasti",
    "UP46": "Balrampur",
    "UP47": "Ambedkar Nagar",
    "UP50": "Azamgarh",
    "UP51": "Basti",
    "UP52": "Deoria",
    "UP53": "Gorakhpur",
    "UP54": "Mau",
    "UP55": "Siddharthnagar",
    "UP56": "Maharajganj",
    "UP57": "Kushinagar (Padrauna)",
    "UP58": "Sant Kabir Nagar",
    "UP60": "Ballia",
    "UP61": "Ghazipur",
    "UP62": "Jaunpur",
    "UP63": "Mirzapur",
    "UP64": "Sonbhadra",
    "UP65": "Varanasi",
    "UP66": "Bhadohi",
    "UP67": "Chandauli",
    "UP70": "Prayagraj (Allahabad)",
    "UP71": "Fatehpur",
    "UP72": "Pratapgarh",
    "UP73": "Kaushambi",
    "UP74": "Kannauj",
    "UP75": "Etawah",
    "UP76": "Farrukhabad",
    "UP77": "Kanpur Dehat",
    "UP78": "Kanpur Nagar",
    "UP79": "Auraiya",
    "UP80": "Agra",
    "UP81": "Aligarh",
    "UP82": "Etah",
    "UP83": "Firozabad",
    "UP84": "Mainpuri",
    "UP85": "Mathura",
    "UP86": "Hathras",
    "UP87": "Kasganj",
    "UP90": "Banda",
    "UP91": "Hamirpur",
    "UP92": "Jalaun (Orai)",
    "UP93": "Jhansi",
    "UP94": "Lalitpur",
    "UP95": "Mahoba",
    "UP96": "Chitrakoot",

    # ----------------------------------------------------
    # TELANGANA (TS)
    # ----------------------------------------------------
    "TS01": "Adilabad",
    "TS02": "Karimnagar",
    "TS03": "Warangal Urban",
    "TS04": "Khammam",
    "TS05": "Nalgonda",
    "TS06": "Mahabubnagar",
    "TS07": "Ranga Reddy (Attapur)",
    "TS08": "Medchal-Malkajgiri",
    "TS09": "Hyderabad Central (Khairatabad)",
    "TS10": "Hyderabad North (Secunderabad)",
    "TS11": "Hyderabad East (Malakpet)",
    "TS12": "Hyderabad South (Kishanbagh)",
    "TS13": "Hyderabad West (Tolichowki)",
    "TS14": "Hyderabad Central (Somajiguda)",
    "TS15": "Sangareddy (Medak)",
    "TS16": "Nizamabad",
    "TS17": "Kamareddy",
    "TS18": "Nirmal",
    "TS19": "Mancherial",
    "TS20": "Kumuram Bheem Asifabad",
    "TS21": "Jagtial",
    "TS22": "Peddapalli",
    "TS23": "Rajanna Sircilla",
    "TS24": "Warangal Rural",
    "TS25": "Jangaon",
    "TS26": "Jayashankar Bhupalpally",
    "TS27": "Mahabubabad",
    "TS28": "Bhadradri Kothagudem",
    "TS29": "Suryapet",
    "TS30": "Yadadri Bhuvanagiri",
    "TS31": "Nagarkurnool",
    "TS32": "Wanaparthy",
    "TS33": "Jogulamba Gadwal",
    "TS34": "Vikarabad",
    "TS35": "Medak",
    "TS36": "Siddipet",

    # ----------------------------------------------------
    # ANDHRA PRADESH (AP)
    # ----------------------------------------------------
    "AP02": "Anantapur",
    "AP03": "Chittoor",
    "AP04": "Kadapa (YSR District)",
    "AP05": "Kakinada (East Godavari)",
    "AP07": "Guntur",
    "AP09": "Nellore",
    "AP16": "Vijayawada (Krishna)",
    "AP21": "Kurnool",
    "AP26": "Nellore",
    "AP31": "Visakhapatnam",
    "AP37": "Eluru (West Godavari)",
    "AP39": "Tirupati",

    # ----------------------------------------------------
    # KERALA (KL)
    # ----------------------------------------------------
    "KL01": "Thiruvananthapuram",
    "KL02": "Kollam",
    "KL03": "Pathanamthitta",
    "KL04": "Alappuzha",
    "KL05": "Kottayam",
    "KL06": "Idukki",
    "KL07": "Ernakulam",
    "KL08": "Thrissur",
    "KL09": "Palakkad",
    "KL10": "Malappuram",
    "KL11": "Kozhikode",
    "KL12": "Wayanad",
    "KL13": "Kannur",
    "KL14": "Kasaragod",
    "KL16": "Attingal",
    "KL17": "Muvattupuzha",
    "KL18": "Vadakara",
    "KL21": "Chala",
    "KL39": "Thripunithura",
    "KL40": "Perumbavoor",

    # ----------------------------------------------------
    # RAJASTHAN (RJ)
    # ----------------------------------------------------
    "RJ01": "Ajmer",
    "RJ02": "Alwar",
    "RJ03": "Banswara",
    "RJ04": "Barmer",
    "RJ05": "Bharatpur",
    "RJ06": "Bhilwara",
    "RJ07": "Bikaner",
    "RJ08": "Bundi",
    "RJ09": "Chittorgarh",
    "RJ10": "Churu",
    "RJ11": "Dholpur",
    "RJ12": "Dungarpur",
    "RJ13": "Sri Ganganagar",
    "RJ14": "Jaipur South",
    "RJ15": "Jaisalmer",
    "RJ16": "Jalore",
    "RJ17": "Jhalawar",
    "RJ18": "Jhunjhunu",
    "RJ19": "Jodhpur",
    "RJ20": "Kota",
    "RJ21": "Nagaur",
    "RJ22": "Pali",
    "RJ23": "Sikar",
    "RJ24": "Sirohi",
    "RJ25": "Sawai Madhopur",
    "RJ26": "Tonk",
    "RJ27": "Udaipur",
    "RJ28": "Baran",
    "RJ29": "Dausa",
    "RJ30": "Rajsamand",
    "RJ31": "Hanumangarh",
    "RJ32": "Kotputli",
    "RJ34": "Karauli",
    "RJ45": "Jaipur North",

    # ----------------------------------------------------
    # HARYANA (HR)
    # ----------------------------------------------------
    "HR01": "Ambala",
    "HR02": "Yamunanagar (Jagadhri)",
    "HR03": "Panchkula",
    "HR04": "Naraingarh",
    "HR05": "Karnal",
    "HR06": "Panipat",
    "HR07": "Kurukshetra",
    "HR08": "Kaithal",
    "HR10": "Sonipat",
    "HR12": "Rohtak",
    "HR13": "Bahadurgarh",
    "HR14": "Jhajjar",
    "HR16": "Bhiwani",
    "HR19": "Charkhi Dadri",
    "HR20": "Hisar",
    "HR24": "Sirsa",
    "HR26": "Gurugram North",
    "HR29": "Ballabgarh",
    "HR51": "Faridabad",
    "HR55": "Gurugram South",
    "HR72": "Gurugram South (Sohna)",

    # ----------------------------------------------------
    # PUNJAB (PB)
    # ----------------------------------------------------
    "PB01": "Chandigarh (Punjab Registry)",
    "PB02": "Amritsar",
    "PB03": "Bathinda",
    "PB04": "Faridkot",
    "PB05": "Ferozepur",
    "PB06": "Gurdaspur",
    "PB07": "Hoshiarpur",
    "PB08": "Jalandhar",
    "PB09": "Kapurthala",
    "PB10": "Ludhiana",
    "PB11": "Patiala",
    "PB12": "Rupnagar (Ropar)",
    "PB13": "Sangrur",
    "PB65": "SAS Nagar (Mohali)",

    # ----------------------------------------------------
    # WEST BENGAL (WB)
    # ----------------------------------------------------
    "WB01": "Kolkata Central",
    "WB02": "Kolkata South (Beltala)",
    "WB03": "Kolkata North (Ultadanga)",
    "WB04": "Kolkata (Salt Lake)",
    "WB06": "Kolkata East (Kasba)",
    "WB11": "Howrah",
    "WB15": "Hooghly",
    "WB19": "Alipore (South 24 Parganas)",
    "WB23": "Barrackpore",
    "WB25": "Barasat (North 24 Parganas)",
    "WB29": "Tamluk (East Midnapore)",
    "WB33": "Midnapore (West Midnapore)",
    "WB37": "Asansol",
    "WB39": "Durgapur",
    "WB41": "Burdwan",
    "WB51": "Siliguri",
    "WB73": "Jalpaiguri",

    # ----------------------------------------------------
    # MADHYA PRADESH (MP)
    # ----------------------------------------------------
    "MP04": "Bhopal",
    "MP07": "Gwalior",
    "MP09": "Indore",
    "MP20": "Jabalpur",
    "MP28": "Chhindwara",
    "MP43": "Ratlam",
    "MP48": "Betul",

    # ----------------------------------------------------
    # BIHAR (BR)
    # ----------------------------------------------------
    "BR01": "Patna",
    "BR02": "Gaya",
    "BR03": "Bhojpur (Arrah)",
    "BR04": "Saran (Chhapra)",
    "BR05": "East Champaran (Motihari)",
    "BR06": "Muzaffarpur",
    "BR07": "Darbhanga",
    "BR08": "Munger",
    "BR09": "Begusarai",
    "BR10": "Bhagalpur",
    "BR11": "Purnea",

    # ----------------------------------------------------
    # GOA (GA)
    # ----------------------------------------------------
    "GA01": "Panaji (North Goa)",
    "GA02": "Margao (South Goa)",
    "GA03": "Mapusa",
    "GA04": "Bicholim",
    "GA05": "Ponda",
    "GA06": "Vasco da Gama",
    "GA07": "Panaji",
    "GA08": "Margao",
    "GA09": "Quepem",
    "GA10": "Canacona",
    "GA11": "Pernem",
    "GA12": "Dharbandora",

    # ----------------------------------------------------
    # CHANDIGARH (CH)
    # ----------------------------------------------------
    "CH01": "Chandigarh",
    "CH02": "Chandigarh Commercial",
    "CH03": "Chandigarh",
    "CH04": "Chandigarh",

    # ----------------------------------------------------
    # UTTARAKHAND (UK / UA)
    # ----------------------------------------------------
    "UK01": "Almora",
    "UK02": "Bageshwar",
    "UK03": "Champawat",
    "UK04": "Nainital (Haldwani)",
    "UK05": "Pithoragarh",
    "UK06": "Udham Singh Nagar (Rudrapur)",
    "UK07": "Dehradun",
    "UK08": "Haridwar",
    "UK09": "Tehri Garhwal",
    "UK10": "Uttarkashi",
    "UK11": "Chamoli (Gopeshwar)",
    "UK12": "Pauri Garhwal",
    "UK13": "Rudraprayag",
    "UK14": "Rishikesh",
    "UK15": "Kotdwar",
    "UK16": "Vikas Nagar",
    "UK17": "Roorkee",
    "UK18": "Kashipur",
    "UA07": "Dehradun",
    "UA08": "Haridwar",

    # ----------------------------------------------------
    # ODISHA (OD / OR)
    # ----------------------------------------------------
    "OD01": "Balasore",
    "OD02": "Bhubaneswar",
    "OD03": "Bolangir",
    "OD04": "Chandikhol",
    "OD05": "Cuttack",
    "OD06": "Dhenkanal",
    "OD07": "Ganjam (Chhatrapur)",
    "OD08": "Kalahandi",
    "OD09": "Keonjhar",
    "OD10": "Koraput",
    "OD14": "Rourkela",
    "OD15": "Sambalpur",
    "OD33": "Bhubaneswar North",
    "OR02": "Bhubaneswar",
    "OR05": "Cuttack",

    # ----------------------------------------------------
    # JHARKHAND (JH)
    # ----------------------------------------------------
    "JH01": "Ranchi",
    "JH02": "Hazaribagh",
    "JH03": "Koderma",
    "JH04": "Dumka",
    "JH05": "Jamshedpur (East Singhbhum)",
    "JH06": "Chaibasa (West Singhbhum)",
    "JH07": "Gumla",
    "JH08": "Lohardaga",
    "JH09": "Bokaro",
    "JH10": "Dhanbad",
    "JH11": "Giridih",
    "JH12": "Deoghar",

    # ----------------------------------------------------
    # ASSAM (AS)
    # ----------------------------------------------------
    "AS01": "Guwahati (Kamrup Metro)",
    "AS02": "Nagaon",
    "AS03": "Jorhat",
    "AS04": "Sibsagar",
    "AS05": "Golaghat",
    "AS06": "Dibrugarh",
    "AS07": "Tinsukia",
    "AS12": "Sonitpur (Tezpur)",
    "AS25": "Kamrup Rural",

    # ----------------------------------------------------
    # HIMACHAL PRADESH (HP)
    # ----------------------------------------------------
    "HP01": "Shimla Urban",
    "HP02": "Kangra (Dharamshala)",
    "HP03": "Mandi",
    "HP11": "Kullu",
    "HP12": "Solan",
    "HP14": "Solan",
    "HP17": "Paonta Sahib",
    "HP22": "Hamirpur",
    "HP24": "Bilaspur",
    "HP34": "Manali",
    "HP63": "Shimla Rural",

    # ----------------------------------------------------
    # JAMMU AND KASHMIR (JK)
    # ----------------------------------------------------
    "JK01": "Srinagar",
    "JK02": "Jammu",
    "JK03": "Anantnag",
    "JK04": "Budgam",
    "JK05": "Baramulla",
    "JK08": "Kathua",
    "JK12": "Poonch",
    "JK13": "Pulwama",
    "JK14": "Udhampur",
    "JK21": "Samba",

    # ----------------------------------------------------
    # CHHATTISGARH (CG)
    # ----------------------------------------------------
    "CG02": "Bilaspur",
    "CG04": "Raipur",
    "CG07": "Durg",
    "CG08": "Rajnandgaon",
    "CG10": "Bilaspur",
    "CG12": "Korba",
    "CG13": "Raigarh",
    "CG15": "Surguja (Ambikapur)",
    "CG17": "Bastar (Jagdalpur)",

    # ----------------------------------------------------
    # OTHER UNION TERRITORIES
    # ----------------------------------------------------
    "AN01": "Port Blair",
    "AN02": "Car Nicobar",
    "LA01": "Leh",
    "LA02": "Kargil",
    "PY01": "Puducherry",
    "PY02": "Karaikal",
    "PY03": "Mahe",
    "PY04": "Yanam",
    "DD01": "Daman",
    "DD02": "Diu",
    "DD03": "Dadra & Nagar Haveli (Silvassa)",
    "DN09": "Dadra & Nagar Haveli",
}

# Optical Character Confusion Mapping for RTO Digit Parsing
CONFUSION_TO_DIGIT = {
    'O': '0', 'Q': '0', 'D': '0',
    'I': '1', 'L': '1',
    'Z': '2',
    'S': '5',
    'G': '6',
    'B': '8',
    'T': '7',
    'A': '4'
}


def clean_registration_text(raw_text: Optional[str]) -> str:
    """Removes spaces, hyphens, and punctuation, returning uppercase alphanumeric."""
    if not raw_text:
        return ""
    return re.sub(r'[^A-Za-z0-9]', '', str(raw_text)).upper()


def parse_indian_registration_format(plate_str: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parses and validates Indian vehicle registration structure.
    
    Returns (state_code, rto_part, series_letters, number_digits) or None.
    
    Supported variations:
    1. Standard: e.g., MH02DN8718, MH12FU1014, KA05MB9999
    2. Single digit RTO (e.g. DL1C1234, DL3CCQ0107, MH2A1234)
    3. Short series or vintage plates (e.g. MH01A1234, DL8CN6308)
    4. BH Series (Bharat Series): e.g., 22BH1234AA
    """
    clean = clean_registration_text(plate_str)
    if not clean or len(clean) < 5 or len(clean) > 12:
        return None

    # Check BH Series: YY BH #### XX (e.g., 22BH1234AA)
    bh_match = re.match(r'^(\d{2})BH(\d{4})([A-Z]{1,2})$', clean)
    if bh_match:
        return ("BH", "BH", bh_match.group(3), bh_match.group(2))

    # Standard Indian Pattern: [State: 2 letters][RTO: 1-2 digits or digit+letter][Series: 0-3 letters][Number: 1-4 digits]
    # e.g., MH02DN8718, DL3CCQ0107, DL8CN6308, GJ12FA0735
    std_match = re.match(r'^([A-Z]{2})([0-9]{1,2}|[0-9][A-Z])([A-Z]{0,3})([0-9]{1,4})$', clean)
    if std_match:
        state_code = std_match.group(1)
        if state_code in INDIAN_STATES or state_code == "BH":
            rto_part = std_match.group(2)
            series = std_match.group(3)
            num = std_match.group(4)
            return (state_code, rto_part, series, num)

    # Secondary check: Handle common optical confusion in RTO portion
    # (e.g., MHO2 instead of MH02)
    if len(clean) >= 6 and clean[:2].isalpha():
        state_try = clean[:2]
        if state_try in INDIAN_STATES:
            ch3 = clean[2]
            ch4 = clean[3] if len(clean) > 3 else ""

            # Test if converting position 2/3 to digits forms a standard structure
            ch3_fixed = CONFUSION_TO_DIGIT.get(ch3, ch3)
            ch4_fixed = CONFUSION_TO_DIGIT.get(ch4, ch4)
            fixed_prefix = state_try + ch3_fixed + ch4_fixed + clean[4:]
            
            fixed_match = re.match(r'^([A-Z]{2})([0-9]{1,2}|[0-9][A-Z])([A-Z]{0,3})([0-9]{1,4})$', fixed_prefix)
            if fixed_match:
                return (fixed_match.group(1), fixed_match.group(2), fixed_match.group(3), fixed_match.group(4))

    return None


def lookup_rto_authority(state_code: str, rto_part: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Looks up descriptive RTO authority location without fabricating names.
    
    Returns:
        (formatted_rto_code, authority_description)
        or (formatted_rto_code, None) if code is unknown
        or (None, None) if completely invalid.
    """
    state_code = state_code.upper()
    rto_part = rto_part.upper()

    if state_code == "BH":
        return ("BH", "Central Ministry of Road Transport & Highways (All India)")

    # Build potential keys, e.g. "MH02" or "MH2" -> normalize to "MH02"
    if rto_part.isdigit():
        num_val = int(rto_part)
        code_2digit = f"{state_code}{num_val:02d}"
        formatted_code = f"{state_code}-{num_val:02d}"
    else:
        # e.g. "DL3C"
        code_2digit = f"{state_code}{rto_part}"
        formatted_code = f"{state_code}-{rto_part}"

    # Search in verified authorities dictionary
    if code_2digit in RTO_AUTHORITIES:
        return (formatted_code, RTO_AUTHORITIES[code_2digit])

    # Also try exact unpadded key if different
    alt_key = f"{state_code}{rto_part}"
    if alt_key in RTO_AUTHORITIES:
        return (formatted_code, RTO_AUTHORITIES[alt_key])

    # Known code format but authority location is not verified in dictionary
    return (formatted_code, None)


def resolve_registration_fallback(
    raw_plate: Optional[str],
    candidates: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Pure read-only fallback resolver for number plates not present in the database.
    
    Derives State and RTO Authority from validated registration syntax.
    Unsupported fields (Fuel Type, Vehicle Age, Registration Date) strictly
    return "Not Available" to avoid speculation or fabrication.
    
    Does NOT write to the database or modify existing data.
    """
    default_response = {
        "is_valid_format": False,
        "registration_number": clean_registration_text(raw_plate) or "UNKNOWN",
        "state": "Not Available",
        "state_code": None,
        "rto_authority": "Not Available",
        "rto_code": None,
        "fuel_type": "Not Available",
        "vehicle_age": "Not Available",
        "registration_date": "Not Available",
        "source": "Registration Code Lookup",
        "source_label": "Registration Code Lookup",
        "is_fallback": True,
        "status_message": "No matching record in local database — showing available registration information."
    }

    try:
        # Test primary input first
        test_inputs = []
        if raw_plate:
            test_inputs.append(str(raw_plate).strip())
        if candidates:
            for c in candidates:
                if c and c not in test_inputs:
                    test_inputs.append(str(c).strip())

        parsed = None
        chosen_reg = clean_registration_text(raw_plate) or "UNKNOWN"

        for item in test_inputs:
            p = parse_indian_registration_format(item)
            if p:
                parsed = p
                chosen_reg = clean_registration_text(item)
                break

        if not parsed:
            # Registration structure could not be parsed as a valid Indian plate format
            return default_response

        state_code, rto_part, series, num = parsed

        # 1. State Resolution
        if state_code == "BH":
            state_display = "All India / Bharat Series (BH)"
        elif state_code in INDIAN_STATES:
            state_name = INDIAN_STATES[state_code]
            state_display = f"{state_name} ({state_code})"
        else:
            state_display = "Not Available"

        # 2. RTO Authority Resolution
        formatted_code, authority_name = lookup_rto_authority(state_code, rto_part)

        if authority_name and formatted_code:
            # Descriptive authority name mapped reliably
            rto_display = f"{formatted_code} — {authority_name}"
        elif formatted_code:
            # Code parsed, but exact office name not in local mapping
            rto_display = "Not Available"
        else:
            rto_display = "Not Available"

        return {
            "is_valid_format": True,
            "registration_number": chosen_reg,
            "state": state_display,
            "state_code": state_code,
            "rto_authority": rto_display,
            "rto_code": formatted_code or rto_part,
            "fuel_type": "Not Available",
            "vehicle_age": "Not Available",
            "registration_date": "Not Available",
            "source": "Registration Code Lookup",
            "source_label": "Registration Code Lookup",
            "is_fallback": True,
            "status_message": "No matching record in local database — showing available registration information."
        }

    except Exception as e:
        # Failsafe: Never crash the calling application
        default_response["status_message"] = f"Lookup fallback error: {str(e)}"
        return default_response
